import {useEffect, useState} from 'react';
import {api} from './api';

type Scores = {event_recall:number|null; false_alerts_per_patient_day:number|null; mean_lead_minutes:number|null; median_lead_minutes:number|null; caught_warned_30m_fraction:number|null; brier:number|null};
type Aggregate = {mean:number|null; min:number|null; max:number|null};
type Report = {
  protocol:{run_id:string; reference_version:string; split_seeds:number[]};
  summary:{models:Record<string,Record<keyof Scores,Aggregate>>};
  runs:{seed:number; models:Record<string,{feature_count:number; selected_settings?:Record<string,string|number>; evaluation:Scores}>}[];
};
const labels:Record<string,string> = {tuned_current:'Current + settings tuned on training patients',trend_baseline:'Simple glucose + trend baseline',current:'Current feature specification',plus_meal_timing:'Current + meal timing',plus_premeal_glucose:'Current + pre-meal glucose',tuned_plus_meal_timing:'Current + meal timing · tuned on training patients',tuned_plus_premeal_glucose:'Current + pre-meal glucose · tuned on training patients'};
// Replace a superseded row only when its completed tuned result exists.
const displayedModels = (report:Report) => [
  report.summary.models.tuned_current ? 'tuned_current' : 'current',
  report.summary.models.tuned_plus_meal_timing ? 'tuned_plus_meal_timing' : 'plus_meal_timing',
  report.summary.models.tuned_plus_premeal_glucose ? 'tuned_plus_premeal_glucose' : 'plus_premeal_glucose',
  'trend_baseline',
].filter(key=>Boolean(report.summary.models[key]));
const number=(v:number|null,d=2)=>v==null?'—':v.toFixed(d);
const percent=(v:number|null)=>v==null?'—':`${(v*100).toFixed(2)}%`;

export function ExperimentEvidence(){
  const [report,setReport]=useState<Report|null>(null);
  const [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{let cancelled=false;setError('');api<Report>('/experiments/latest').then(r=>{if(!cancelled)setReport(r);}).catch(e=>{if(!cancelled)setError((e as Error).message);});return()=>{cancelled=true;};},[attempt]);
  return <section className="panel">
    <div className="panel-header"><div><h2>Repeated patient-split research models</h2><p>Feature and settings comparisons · the app deploys one selected model, not the three-run average</p></div>{report&&<a className="button secondary" href="/api/experiments/latest" target="_blank" rel="noreferrer">Comparison report</a>}</div>
    {!report&&!error&&<p className="experiment-note">Loading completed comparisons…</p>}
    {error&&<p className="experiment-note" role="alert">Could not load the research comparison: {error}. If you just updated the app, restart its server. <button className="button secondary" onClick={()=>setAttempt(x=>x+1)}>Retry</button></p>}
    {report&&<>
      <p className="experiment-note">{report.runs.length} patient assignments × {displayedModels(report).length} displayed models. Each run: 60 training / 10 calibration / 10 threshold selection / 20 evaluation patients. Each model is trained afresh. The current specification already includes food nutrients and medication records.</p>
      <div className="table-wrap"><table><thead><tr><th>Feature set</th><th>Mean episode recall</th><th>Mean false alerts / day</th><th>Mean warning</th><th>Caught ≥30 min early</th><th>Mean Brier</th></tr></thead><tbody>{displayedModels(report).map(key=>{const m=report.summary.models[key];return <tr key={key}><td><b>{labels[key]||key}</b><small>{report.runs[0]?.models[key]?.feature_count} features · research comparison</small></td><td>{percent(m.event_recall.mean)}<small>Run range: {percent(m.event_recall.min)}–{percent(m.event_recall.max)}</small></td><td>{number(m.false_alerts_per_patient_day.mean)}<small>Run range: {number(m.false_alerts_per_patient_day.min)}–{number(m.false_alerts_per_patient_day.max)}</small></td><td>{number(m.mean_lead_minutes.mean)} min</td><td>{percent(m.caught_warned_30m_fraction.mean)}</td><td>{number(m.brier.mean,5)}</td></tr>;})}</tbody></table></div>
      <p className="experiment-note">Values above are unweighted averages of run results. Warning times and ≥30-minute percentages concern caught episodes. Patients overlap across runs; ranges are descriptive, not confidence intervals. This cohort was previously inspected during development.</p>
      <details className="experiment-details"><summary>Inspect every run and its median warning</summary><div className="table-wrap"><table><thead><tr><th>Split seed</th><th>Feature set</th><th>Episode recall</th><th>False alerts / day</th><th>Median warning</th><th>Mean warning</th></tr></thead><tbody>{report.runs.flatMap(run=>displayedModels(report).map(key=>{const m=run.models[key];return <tr key={`${run.seed}-${key}`}><td>{run.seed}</td><td>{labels[key]||key}{m.selected_settings&&<small>Inner-CV selection: {Object.entries(m.selected_settings).map(([k,v])=>`${k}: ${v}`).join('; ')}</small>}</td><td>{percent(m.evaluation.event_recall)}</td><td>{number(m.evaluation.false_alerts_per_patient_day)}</td><td>{number(m.evaluation.median_lead_minutes,0)} min</td><td>{number(m.evaluation.mean_lead_minutes)} min</td></tr>;}))}</tbody></table></div></details>
      <p className="experiment-note">Reference model: {report.protocol.reference_version}. Comparison: {report.protocol.run_id}. Compare feature sets within the same split. The active model’s results above describe its single evaluation group; these averages describe three overlapping patient assignments.</p>
    </>}
  </section>;
}
