"""Lossless directed topology import; every unmeasured condition remains unknown.

OSM is a map source, not an accessibility audit. Tags are preserved as candidates,
not confirmed evidence. Shared OSM nodes connect only within the same level.
Parallel ways stay parallel, geometrical intersections never manufacture nodes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from typing import Any

MAX_ELEMENTS = 100_000


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _base(payload, publisher, url, licence):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(raw.encode()).hexdigest()
    return {
        'version': f'import-{sha[:16]}', 'layer': 'observed', 'status': 'staged',
        'valid_from': _stamp(), 'valid_until': None, 'nodes': [], 'edges': [],
        'assets': [], 'places': [], 'entrances': [], 'evidence': [], 'restrictions': [],
        'profiles': [], 'origins': [],
        'source': {'publisher': publisher, 'url': url, 'published_at': None,
                   'fetched_at': _stamp(), 'observed_at': None, 'sha256': sha,
                   'licence': licence, 'raw': payload},
        'quality': {'warnings': [], 'candidates': [], 'coverage': 'unverified',
                    'field_audit_required': True, 'confirmed_relations': 0},
    }


def _coord(lon, lat):
    lon, lat = float(lon), float(lat)
    if not math.isfinite(lon + lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError('Współrzędne muszą być skończonym WGS84.')
    return lon, lat


def _length(a, b):
    # WGS84 geodesic when pyproj is available; spherical fallback is explicitly
    # tagged by caller and is used only for conservative source geometry estimates.
    try:
        from pyproj import Geod
        return abs(Geod(ellps='WGS84').inv(a[0], a[1], b[0], b[1])[2])
    except ImportError:
        r = 6_371_008.8
        p1, p2 = math.radians(a[1]), math.radians(b[1])
        dlat, dlon = p2 - p1, math.radians(b[0] - a[0])
        return 2*r*math.asin(min(1, math.sqrt(math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2)))


def _tag_number(value, unit=None):
    if value is None:
        return None
    try:
        return float(str(value).strip().removesuffix(unit or '').strip())
    except ValueError:
        return None


def import_osm(payload: dict, url='file:overpass.json') -> dict:
    elements = payload.get('elements')
    if not isinstance(elements, list) or len(elements) > MAX_ELEMENTS:
        raise ValueError('Niepoprawny lub zbyt duży wycinek Overpass.')
    graph = _base(payload, 'OpenStreetMap contributors', url, 'ODbL-1.0')
    by_id = {e['id']: e for e in elements if e.get('type') == 'node'}
    node_ids, assets = set(), set()
    pedestrian = {'footway', 'path', 'pedestrian', 'steps', 'living_street', 'crossing', 'corridor', 'bridleway', 'track'}
    for way in elements:
        if way.get('type') != 'way':
            continue
        tags, refs = way.get('tags', {}), way.get('nodes', [])
        highway = tags.get('highway')
        if highway not in pedestrian:
            if tags.get('sidewalk') not in (None, 'no', 'none') or any(k.startswith('sidewalk:') for k in tags):
                graph['quality']['warnings'].append({'way_id': way['id'], 'reason': 'sidewalk_on_road_requires_geometry_audit', 'tags': tags})
            continue
        if tags.get('foot') in ('no', 'private') or tags.get('access') == 'private':
            graph['quality']['warnings'].append({'way_id': way['id'], 'reason': 'access_prohibited', 'tags': tags})
            continue
        level = tags.get('level', tags.get('layer', '0'))
        if ';' in str(level):
            graph['quality']['warnings'].append({'way_id': way['id'], 'reason': 'ambiguous_level'})
            continue
        asset_id = f'osm-way-{way["id"]}'
        asset = {'id': asset_id, 'name': tags.get('name', f'Przejście OSM {way["id"]}'),
                 'failure_group_id': f'tunnel-{way["id"]}' if tags.get('tunnel') == 'yes' else None,
                 'kind': highway, 'source_tags': tags, 'source_id': str(way['id'])}
        graph['assets'].append(asset)
        assets.add(asset_id)
        features = {'steps': highway == 'steps', 'width_m': _tag_number(tags.get('width'), 'm'),
                    'slope_pct': _tag_number(tags.get('incline'), '%'), 'surface': tags.get('surface')}
        for feature, value in features.items():
            if value is not None:
                graph['quality']['candidates'].append({'asset_id': asset_id, 'feature': feature, 'value': value, 'method': 'OSM tag, requires review'})
        for index, (u, v) in enumerate(zip(refs, refs[1:])):
            if u not in by_id or v not in by_id:
                graph['quality']['warnings'].append({'way_id': way['id'], 'reason': 'missing_osm_node'})
                continue
            for ref in (u, v):
                node_id = f'osm-node-{ref}@{level}'
                if node_id not in node_ids:
                    node = by_id[ref]
                    lon, lat = _coord(node['lon'], node['lat'])
                    graph['nodes'].append({'id': node_id, 'lon': lon, 'lat': lat, 'level': level, 'source_id': str(ref), 'source_tags': node.get('tags', {})})
                    node_ids.add(node_id)
            a = _coord(by_id[u]['lon'], by_id[u]['lat'])
            b = _coord(by_id[v]['lon'], by_id[v]['lat'])
            length = _length(a, b)
            directions = [(u, v, a, b, 'f')]
            if tags.get('oneway:foot') != 'yes':
                directions.append((v, u, b, a, 'r'))
            if tags.get('oneway:foot') == '-1':
                directions = [(v, u, b, a, 'r')]
            for start, end, ca, cb, direction in directions:
                graph['edges'].append({'id': f'{asset_id}-{index}-{direction}', 'u': f'osm-node-{start}@{level}', 'v': f'osm-node-{end}@{level}',
                    'asset_id': asset_id, 'length_m': round(length, 3), 'duration_s': round(length/0.8, 3), 'duration_assumption': '0.8 m/s; editable in audited import',
                    'geometry': [ca, cb], 'level': level, 'side': tags.get('footway'), 'direction': direction,
                    'slope_direction': 1 if direction == 'f' else -1, 'source_tags': tags})
    # Entrance remains a physical target only if its exact OSM node is in the
    # pedestrian topology. Never snap across a road, fence, or to a centroid.
    for ref, node in by_id.items():
        tags = node.get('tags', {})
        if not tags.get('entrance') or tags['entrance'] == 'no':
            continue
        level = tags.get('level', tags.get('layer', '0'))
        nid = f'osm-node-{ref}@{level}'
        if nid not in node_ids:
            graph['quality']['warnings'].append({'node_id': ref, 'reason': 'entrance_not_connected'})
            continue
        aid, pid, eid = f'entrance-asset-{ref}', f'place-{ref}', f'entrance-{ref}'
        graph['assets'].append({'id': aid, 'name': tags.get('name', 'Wejście wymagające audytu'), 'kind': 'entrance', 'source_tags': tags})
        graph['places'].append({'id': pid, 'name': tags.get('name', f'Wejście OSM {ref}'), 'category': tags.get('amenity', 'entrance'), 'entrance_ids': [eid]})
        graph['entrances'].append({'id': eid, 'asset_id': aid, 'node_id': nid, 'place_id': pid})
    graph['quality'].update(node_count=len(graph['nodes']), edge_count=len(graph['edges']), entrance_count=len(graph['entrances']))
    return graph


def import_geojson(payload: dict, url='file:graph.geojson') -> dict:
    if payload.get('type') != 'FeatureCollection' or not isinstance(payload.get('features'), list):
        raise ValueError('Wymagana kolekcja GeoJSON FeatureCollection.')
    if len(payload['features']) > MAX_ELEMENTS:
        raise ValueError('Za dużo obiektów.')
    graph = _base(payload, 'Import operatora', url, 'do potwierdzenia')
    nodes, assets = {}, {}
    for feature in payload['features']:
        prop, geom = feature.get('properties') or {}, feature.get('geometry') or {}
        kind = prop.get('kind', 'edge')
        if geom.get('type') == 'Point':
            if not prop.get('id'):
                raise ValueError('Punkt wymaga stabilnego id.')
            lon, lat = _coord(*geom['coordinates'][:2])
            candidate = {'id': prop['id'], 'lon': lon, 'lat': lat, 'level': str(prop.get('level', '0'))}
            previous = nodes.get(prop['id'])
            if previous and (previous['level'] != candidate['level'] or _length([previous['lon'], previous['lat']], [lon, lat]) > 0.5):
                raise ValueError(f'Sprzeczna geometria lub poziom węzła {prop["id"]}.')
            nodes[prop['id']] = candidate
            if kind == 'entrance':
                aid = prop.get('asset_id', f'entrance-{prop["id"]}')
                pid = prop.get('place_id', f'place-{prop["id"]}')
                assets[aid] = {'id': aid, 'name': prop.get('name', 'Wejście'), 'kind': 'entrance'}
                graph['places'].append({'id': pid, 'name': prop.get('name', 'Wejście'), 'category': prop.get('category', 'service'), 'entrance_ids': [prop['id']]})
                graph['entrances'].append({'id': prop['id'], 'node_id': prop['id'], 'asset_id': aid, 'place_id': pid})
        elif geom.get('type') == 'LineString':
            if not all(prop.get(key) for key in ('id', 'u', 'v', 'asset_id')):
                raise ValueError('Odcinek wymaga id, u, v i asset_id. Przecięcia geometrii nie tworzą przejść.')
            coords = [_coord(*c[:2]) for c in geom['coordinates']]
            if len(coords) < 2:
                raise ValueError('Odcinek wymaga dwóch punktów.')
            length = sum(_length(a, b) for a, b in zip(coords, coords[1:]))
            aid = prop['asset_id']
            assets[aid] = {'id': aid, 'name': prop.get('name', aid), 'kind': prop.get('asset_kind', 'footway'), 'failure_group_id': prop.get('failure_group_id')}
            for nid, c in ((prop['u'], coords[0]), (prop['v'], coords[-1])):
                candidate = {'id': nid, 'lon': c[0], 'lat': c[1], 'level': str(prop.get('level', '0'))}
                if nid in nodes and (nodes[nid]['level'] != candidate['level'] or _length([nodes[nid]['lon'], nodes[nid]['lat']], c) > 0.5):
                    raise ValueError(f'Sprzeczna geometria lub poziom węzła {nid}.')
                nodes[nid] = candidate
            graph['edges'].append({'id': prop['id'], 'u': prop['u'], 'v': prop['v'], 'asset_id': aid, 'geometry': coords,
                'length_m': float(prop.get('length_m', length)), 'duration_s': float(prop.get('duration_s', length/0.8)), 'level': prop.get('level', '0'), 'side': prop.get('side')})
            # Each direction must be explicit in import. No inferred reverse edges.
        else:
            raise ValueError('Dozwolone są wyłącznie punkty i odcinki LineString.')
    graph['nodes'], graph['assets'] = list(nodes.values()), list(assets.values())
    graph['quality']['warnings'].append({'reason': 'all_features_require_evidence_review'})
    return graph


def import_csv(text: str) -> dict:
    """Import notices as candidates; a moderator supplies missing geometry/impact."""
    if len(text.encode('utf-8')) > 2_000_000:
        raise ValueError('CSV przekracza 2 MB.')
    rows = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    if not rows or len(rows) > 5000:
        raise ValueError('CSV musi zawierać od 1 do 5000 rekordów.')
    candidates = []
    for row in rows:
        if not row.get('title') or not row.get('source_url'):
            raise ValueError('CSV wymaga kolumn title oraz source_url.')
        for field in ('start', 'end'):
            if row.get(field):
                dt = datetime.fromisoformat(row[field].replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    raise ValueError('Terminy CSV wymagają jawnej strefy czasu.')
        candidates.append({key: row.get(key) or None for key in ('title', 'source_url', 'publisher', 'published_at', 'asset_id', 'start', 'end', 'location_text', 'side', 'level', 'pedestrian_impact', 'quote')})
    return {'type': 'notice_candidates', 'status': 'needs_review', 'candidates': candidates,
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'raw': text, 'fetched_at': _stamp()}
