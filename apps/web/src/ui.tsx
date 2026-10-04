import { AlertTriangle, ArrowRight, CheckCircle2, Info, Loader2, LockKeyhole, X } from 'lucide-react';
import {useEffect,useRef,type ReactNode} from 'react';
import { statusLabel } from './api';

export function IconMark({children, tone = 'navy'}: {children: ReactNode; tone?: string}) { return <span className={`icon-mark ${tone}`}>{children}</span>; }
export function Badge({children, tone = 'neutral'}: {children: ReactNode; tone?: string}) { return <span className={`badge ${tone}`}>{children}</span>; }
export function Status({value}: {value?: string}) {
  const tone = ['confirmed','confirmed_route','completed','succeeded','published','OPTIMAL','FEASIBLE','effect_reviewed'].includes(value || '') ? 'green'
    : ['blocked','barrier','known_barrier','failed','rejected','INFEASIBLE'].includes(value || '') ? 'red'
    : ['possible','possible_route','limit','uncertain','needs_review','needs_recheck','located_unverified','expired','UNKNOWN','conflicted','pending_review'].includes(value || '') ? 'amber' : 'neutral';
  return <Badge tone={tone}>{statusLabel(value)}</Badge>;
}
export function Notice({children, tone = 'info'}: {children: ReactNode; tone?: string}) { return <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>{tone === 'success' ? <CheckCircle2 size={18}/> : tone === 'error' || tone === 'warning' ? <AlertTriangle size={18}/> : <Info size={18}/>}<div>{children}</div></div>; }
export function Empty({title, children, action}: {title: string; children?: ReactNode; action?: ReactNode}) { return <div className="empty"><span className="empty-icon"><Info size={25}/></span><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>; }
export function Loading({children = 'Wczytywanie danych…'}: {children?: ReactNode}) { return <div className="loading" role="status"><Loader2 size={22} className="spin"/>{children}</div>; }
export function Button({children, onClick, disabled, kind = 'primary', type = 'button', className = '', busy = false}: {children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: string; type?: 'button'|'submit'; className?: string; busy?: boolean}) { return <button type={type} className={`btn ${kind} ${className}`} onClick={onClick} disabled={disabled || busy}>{busy && <Loader2 size={16} className="spin"/>}{children}</button>; }
export function Field({label, hint, children}: {label: string; hint?: string; children: ReactNode}) { return <label className="field"><span className="field-label">{label}</span>{children}{hint && <span className="field-hint">{hint}</span>}</label>; }
export function CardTitle({eyebrow, title, action}: {eyebrow?: string; title: string; action?: ReactNode}) { return <div className="card-title"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>{action}</div>; }
export function PageHeading({eyebrow, title, description, action}: {eyebrow: string; title: string; description: string; action?: ReactNode}) { return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>; }
export function AuthGate({loggedIn, role, allowed = ['operator','admin'], onLogin, children}: {loggedIn: boolean; role?: string; allowed?: string[]; onLogin: () => void; children: ReactNode}) {
  return loggedIn && allowed.includes(role || '') ? <>{children}</> : <div className="auth-gate"><LockKeyhole size={24}/><div><h3>{loggedIn ? 'Potrzebna jest inna rola' : 'Zaloguj się do stanowiska operatora'}</h3><p>{loggedIn ? 'Ta część procesu wymaga uprawnień operatora lub administratora.' : 'Publicznie możesz sprawdzić dojście i wysłać zgłoszenie. Publikacja danych wymaga uprawnień.'}</p></div>{!loggedIn && <Button onClick={onLogin}>Zaloguj się <ArrowRight size={16}/></Button>}</div>;
}
export function Modal({title, children, onClose}: {title: string; children: ReactNode; onClose: () => void}) {
  const previousFocus=useRef(document.activeElement as HTMLElement|null);
  const modal=useRef<HTMLElement>(null);
  useEffect(()=>{modal.current?.querySelector<HTMLElement>('button')?.focus();return()=>{if(previousFocus.current?.isConnected)previousFocus.current.focus();};},[]);
  return <div className="modal-backdrop" onClick={onClose}><section ref={modal} className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()} onKeyDown={e => {
    if (e.key === 'Escape') {e.preventDefault();e.stopPropagation();onClose();}
    if (e.key === 'Tab') {
      const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]')).filter(item=>item.getClientRects().length);
      const first = items[0], last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  }}><div className="modal-head"><h2>{title}</h2><button autoFocus className="icon-button" aria-label="Zamknij okno" onClick={onClose}><X size={21}/></button></div>{children}</section></div>;
}
