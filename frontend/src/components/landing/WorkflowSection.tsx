import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useLayoutEffect, useRef } from 'react';

gsap.registerPlugin(ScrollTrigger);

import { CheckCircle, Upload, Zap } from 'lucide-react';

export function WorkflowSection() {
  const containerRef = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const ctx = gsap.context(() => {
      const lines = gsap.utils.toArray('.transcript-line');
      
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: containerRef.current,
          start: 'top 30%',
          end: '+=100%',
          pin: true,
          scrub: 1,
        }
      });

      lines.forEach((line: any, i) => {
        tl.fromTo(line, 
          { opacity: 0, y: 20 },
          { opacity: 1, y: 0, duration: 1, ease: 'none' }
        );
        // Small pause between lines for realism
        tl.to({}, { duration: 0.5 });
      });

    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <section className="workflow-section" id="how-it-works" ref={containerRef}>
      <div className="workflow-terminal">
        <div className="term-header">
          <span className="term-btn red"></span>
          <span className="term-btn yellow"></span>
          <span className="term-btn green"></span>
          <span className="term-title">system.log</span>
        </div>
        <div className="term-body">
          <div className="transcript-line">
            <Upload size={16} className="log-icon" />
            <span className="log-timestamp">[00:00:01]</span>
            <strong className="log-step">INPUT</strong>
            <span className="log-text">Received raw product spec/PRD from user.</span>
          </div>
          
          <div className="transcript-line">
            <Zap size={16} className="log-icon accent" />
            <span className="log-timestamp">[00:00:02]</span>
            <strong className="log-step">ATTACK</strong>
            <span className="log-text">LangGraph multi-agent pipeline initiated. Streaming live critiques over WebSockets.</span>
          </div>
          
          <div className="transcript-line">
            <CheckCircle size={16} className="log-icon success" />
            <span className="log-timestamp">[00:00:05]</span>
            <strong className="log-step">SYNTHESIZE</strong>
            <span className="log-text">Moderator resolved 14 conflicting critiques. Hardened specification generated.</span>
          </div>
          
          <div className="transcript-line cursor">
            <span className="cursor-blink">▌</span>
          </div>
        </div>
      </div>
    </section>
  );
}
