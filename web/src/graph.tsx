import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import { didLabel } from './data'
import type { Investigation } from './types'

export default function Graph({ alert, selected, choose }: { alert: Investigation; selected: number; choose: (index: number) => void }) {
  const element = useRef<HTMLDivElement>(null)
  const graph = useRef<cytoscape.Core>(null)
  useEffect(() => {
    const instance = cytoscape({
      container: element.current!,
      elements: [
        ...alert.evidence.accounts.map(id => ({ data: { id, label: didLabel(id) } })),
        ...alert.evidence.edges.map((edge, i) => ({ data: { id: 'edge' + i, source: edge.source, target: edge.target }, classes: edge.matches.length ? 'match' : 'interaction' })),
      ],
      layout: { name: 'circle', padding: 55 },
      minZoom: 0.15, maxZoom: 4, boxSelectionEnabled: false, autoungrabify: true,
      style: [
        { selector: 'node', style: { label: 'data(label)', 'background-color': '#a8c773', color: '#344334', width: 22, height: 22,
          'font-size': 12, 'text-margin-y': 8, 'text-valign': 'bottom', 'border-width': 2, 'border-color': '#f6faef' } },
        { selector: 'edge', style: { width: 2, 'line-color': '#a4ad9d', 'curve-style': 'straight' } },
        { selector: '.interaction', style: { 'line-style': 'dashed' } },
        { selector: '.active-edge', style: { 'line-color': '#527834', width: 4 } },
      ],
    })
    graph.current = instance
    instance.on('tap', 'edge', e => choose(Number(e.target.id().slice(4))))
    const observer = new ResizeObserver(() => { instance.resize(); instance.fit(undefined, 45) })
    if (element.current) observer.observe(element.current)
    return () => { observer.disconnect(); graph.current = null; instance.destroy() }
  }, [alert.evidence, choose])
  useEffect(() => {
    graph.current?.edges().removeClass('active-edge')
    graph.current?.getElementById('edge' + selected).addClass('active-edge')
  }, [alert.evidence, selected])
  return <div className="graph-wrap"><div ref={element} className="network" aria-label="Account network. Relationship selector and evidence follow." />
    <div className="graph-key"><span><i />Synchronized activity</span><span><i className="dashed" />Public interaction only</span>
      <button className="button secondary" onClick={() => graph.current?.fit(undefined, 40)}>Fit graph</button></div></div>
}
