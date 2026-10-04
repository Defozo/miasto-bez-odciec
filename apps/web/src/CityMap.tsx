import { useEffect, useMemo, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { FeatureCollection, Feature, LineString } from 'geojson';
import { Layers3, MapPin, Maximize2, Minus, Plus } from 'lucide-react';
import { type RecordData, rows } from './api';
import 'maplibre-gl/dist/maplibre-gl.css';
maplibregl.setWorkerUrl(mapWorkerUrl);
export type MapViewport={center:[number,number];zoom:number;bearing:number;pitch:number};

export default function CityMap({graph, route, selectedTime, onSelectAsset, compact = false,viewport,onViewportChange}: {graph: RecordData; route?: RecordData | null; selectedTime?: string; onSelectAsset?: (id: string) => void; compact?: boolean;viewport?:MapViewport;onViewportChange?:(value:MapViewport)=>void}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState(false);
  const [renderedEdges,setRenderedEdges]=useState(0);
  const [showConstraints, setShowConstraints] = useState(true);
  const [cameraStamp,setCameraStamp]=useState('');const synchronizing=useRef(false);
  const viewportRef=useRef(viewport);viewportRef.current=viewport;const viewportChange=useRef(onViewportChange);viewportChange.current=onViewportChange;
  const graphRef = useRef(graph); graphRef.current = graph;
  const assetSelectRef = useRef(onSelectAsset); assetSelectRef.current = onSelectAsset;
  const lines = useMemo<FeatureCollection<LineString>>(() => {
    const seen = new Set<string>();
    const instant = new Date(selectedTime || graph.clock).valueOf();
    const restrictions = rows(graph.restrictions);
    const path = new Set(route?.path || []);
    const features: Feature<LineString>[] = [];
    for (const edge of rows(graph.edges)) {
      if (!Array.isArray(edge.geometry) || edge.geometry.length < 2) continue;
      const key = [edge.u,edge.v].sort().join(':') + edge.asset_id;
      if (seen.has(key) && !path.has(edge.id)) continue; seen.add(key);
      const affected = restrictions.some(r => r.asset_id === edge.asset_id && new Date(r.start).valueOf() <= instant && new Date(r.end).valueOf() > instant);
      features.push({type:'Feature', properties:{id:edge.id, asset_id:edge.asset_id, name:edge.name, active:affected, route:path.has(edge.id)}, geometry:{type:'LineString',coordinates:edge.geometry}});
    }
    return {type:'FeatureCollection',features};
  }, [graph,route,selectedTime]);

  const fit = () => {
    const coords = rows(graphRef.current.nodes).filter(n => typeof n.lon === 'number' && typeof n.lat === 'number');
    if (!coords.length || !mapRef.current) return;
    const bounds = new maplibregl.LngLatBounds(); coords.forEach(n => bounds.extend([n.lon,n.lat]));
    mapRef.current.fitBounds(bounds, {padding:{top:75,bottom:75,left:70,right:100},duration:0,maxZoom:16});
  };

  useEffect(() => {
    if (!container.current) return;
    let map: MapLibreMap;
    try {
      map = new maplibregl.Map({container:container.current,style:{version:8,sources:{},layers:[{id:'ground',type:'background',paint:{'background-color':'#e9eef3'}}]},center:[19.930,50.0705],zoom:14.9,attributionControl:false,cooperativeGestures:true,renderWorldCopies:false});
    } catch { setMapError(true); return; }
    mapRef.current = map;
    map.on('move',()=>{const center=map.getCenter(),current:MapViewport={center:[center.lng,center.lat],zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()};setCameraStamp(JSON.stringify([center.lng,center.lat,current.zoom,current.bearing,current.pitch].map(value=>Number(value.toFixed(5)))));if(!synchronizing.current)viewportChange.current?.(current);});
    map.on('idle',()=>{if(map.getLayer('corridor-lines'))setRenderedEdges(map.queryRenderedFeatures({layers:['corridor-lines']}).length);});
    map.on('error',()=>setMapError(true));
    map.on('load', () => {
      map.addSource('corridors', {type:'geojson',data:{type:'FeatureCollection',features:[]}});
      map.addLayer({id:'corridor-shadow',type:'line',source:'corridors',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#d2dce5','line-width':28}});
      map.addLayer({id:'corridor-casing',type:'line',source:'corridors',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#ffffff','line-width':23}});
      map.addLayer({id:'corridor-lines',type:'line',source:'corridors',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#64778a','line-width':4}});
      map.addLayer({id:'constraint-lines',type:'line',source:'corridors',filter:['==',['get','active'],true],layout:{'line-cap':'round'},paint:{'line-color':'#b64b32','line-width':6,'line-dasharray':[1.6,1.2]}});
      map.addLayer({id:'route-lines',type:'line',source:'corridors',filter:['==',['get','route'],true],layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#245d91','line-width':7}});
      map.on('click','corridor-lines',e => { const id = e.features?.[0]?.properties?.asset_id; if (id) assetSelectRef.current?.(id); });
      map.on('mouseenter','corridor-lines',() => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave','corridor-lines',() => { map.getCanvas().style.cursor = ''; });
      if(viewportRef.current)map.jumpTo(viewportRef.current);else fit(); setReady(true);
    });
    const resize = new ResizeObserver(() => map.resize()); resize.observe(container.current);
    return () => { resize.disconnect(); markers.current.forEach(marker => marker.remove()); markers.current=[]; map.remove(); mapRef.current=null; };
  }, []);

  useEffect(()=>{const map=mapRef.current;if(!ready||!map||!viewport)return;const center=map.getCenter();if(Math.abs(center.lng-viewport.center[0])+Math.abs(center.lat-viewport.center[1])+Math.abs(map.getZoom()-viewport.zoom)+Math.abs(map.getBearing()-viewport.bearing)+Math.abs(map.getPitch()-viewport.pitch)<0.000001)return;synchronizing.current=true;map.jumpTo(viewport);synchronizing.current=false;},[ready,viewport]);

  useEffect(() => {
    const map = mapRef.current; if (!ready || !map) return;
    (map.getSource('corridors') as GeoJSONSource).setData(lines);
    map.setLayoutProperty('constraint-lines','visibility',showConstraints ? 'visible' : 'none');
    map.setPaintProperty('route-lines','line-dasharray', route?.status === 'possible' ? [2,1.2] : [1,0]);
    markers.current.forEach(marker => marker.remove());
    markers.current = rows(graph.nodes).filter(n => typeof n.lon === 'number' && typeof n.lat === 'number').map(node => {
      const element = document.createElement('div');
      const origin = rows(graph.origins).some(o => (o.node_id||o.id) === node.id);
      const entrance = rows(graph.entrances).some(o => o.node_id === node.id);
      element.className = `map-node ${entrance ? 'destination' : origin ? 'origin' : 'junction'}`;
      const icon = document.createElement('span'); icon.className = 'map-node-dot'; icon.textContent = entrance ? '+' : origin ? (node.id.includes('west') ? 'A' : 'B') : '';
      const text = document.createElement('span'); text.className = 'map-node-label'; text.textContent = node.name || node.id;
      element.append(icon,text); element.setAttribute('aria-hidden','true');
      return new maplibregl.Marker({element,anchor:'center'}).setLngLat([node.lon,node.lat]).addTo(map);
    });
  }, [ready,lines,graph,showConstraints,route]);

  return <div className={`city-map ${compact ? 'compact' : ''}`} data-rendered-edges={renderedEdges} data-map-camera={cameraStamp}>
    <div ref={container} className="map-canvas" role="img" aria-label="Schemat sieci dojść. Te same odcinki i ograniczenia są dostępne na liście tekstowej."/>
    <div className="map-caption"><MapPin size={14}/><span>{graph.layer==='fixture'?'DEMO':'Opublikowany obszar'}</span><span className="map-caption-separator"/>{graph.layer==='fixture'?'Kraków · ilustracja sieci':'Sieć piesza i wejścia'}</div>
    <div className="map-controls" aria-label="Sterowanie mapą"><button aria-label="Przybliż mapę" onClick={() => mapRef.current?.zoomIn()}><Plus size={18}/></button><button aria-label="Oddal mapę" onClick={() => mapRef.current?.zoomOut()}><Minus size={18}/></button><button aria-label="Pokaż cały obszar" onClick={fit}><Maximize2 size={17}/></button><button aria-label="Pokaż ograniczenia" aria-pressed={showConstraints} onClick={() => setShowConstraints(v => !v)}><Layers3 size={18}/></button></div>
    <div className="map-legend"><span><i className="legend-line"/>{graph.layer==='fixture'?'Dojścia':'Sieć dojść'}</span><span><i className="legend-line red"/>Ograniczenie</span>{(route?.path?.length||0)>0 && <span><i className={`legend-line green ${route?.status === 'possible' ? 'dashed' : ''}`}/>{route?.status === 'possible' ? 'Możliwe dojście' : 'Wyznaczona trasa'}</span>}</div>
    <span className="map-attribution">{graph.layer==='fixture'?'Dane demo · CC0':'Źródła i licencje w rejestrze'} · MapLibre</span>
    {mapError && <div className="map-fallback">Mapa nie jest dostępna w tej przeglądarce. Użyj pełnej listy tekstowej poniżej.</div>}
  </div>;
}
