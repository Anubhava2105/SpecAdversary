import { useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);
import { Search, Swords, Diamond, Settings, Shield } from 'lucide-react';

const CRITICS = [
  { id: 'assumption', title: 'Assumption Hunter', desc: 'Flags unverified claims masquerading as facts.', Icon: Search },
  { id: 'competitor', title: 'Competitor Simulator', desc: 'Attacks your feature set from the perspective of a ruthless rival.', Icon: Swords },
  { id: 'economics', title: 'Economics Tester', desc: 'Stress-tests your unit economics and pricing models.', Icon: Diamond },
  { id: 'feasibility', title: 'Feasibility Auditor', desc: 'Pinpoints technical bottlenecks and scalability risks.', Icon: Settings },
  { id: 'security', title: 'Security Auditor', desc: 'Looks for data leaks and compliance risks.', Icon: Shield },
];

export function DossierSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const itemsRef = useRef<(HTMLDivElement | null)[]>([]);

  useLayoutEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    let ctx = gsap.context(() => {
      // Entrance stagger using ScrollTrigger batch
      gsap.set('.dossier-item', { opacity: 0, x: -30 });
      ScrollTrigger.batch('.dossier-item', {
        onEnter: batch => gsap.to(batch, { opacity: 1, x: 0, stagger: 0.1, duration: 0.6, ease: 'power2.out' }),
        start: 'top 85%'
      });
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  const handleMouseEnter = (idx: number) => {
    const item = itemsRef.current[idx];
    if (!item) return;
    
    // Sequence hover animation: Icon pulses first, then border glows
    const tl = gsap.timeline();
    const icon = item.querySelector('.dossier-icon');
    
    tl.to(icon, { scale: 1.15, color: '#d5ff4d', duration: 0.2, ease: 'back.out(2)' })
      .to(item, { borderColor: '#d5ff4d', boxShadow: '0 0 12px rgba(213,255,77,0.15)', duration: 0.3 }, "-=0.12");
  };

  const handleMouseLeave = (idx: number) => {
    const item = itemsRef.current[idx];
    if (!item) return;
    
    const icon = item.querySelector('.dossier-icon');
    gsap.to([item, icon], { scale: 1, color: '#a7a991', borderColor: '#3b3d36', boxShadow: 'none', duration: 0.3, ease: 'power2.out' });
  };

  return (
    <section className="dossier-section" id="features" ref={sectionRef}>
      <h2>Meet Your Worst Critics.</h2>
      <div className="dossier-list">
        {CRITICS.map((critic, i) => (
          <div 
            key={critic.id} 
            className="dossier-item" 
            ref={el => { itemsRef.current[i] = el; }}
            onMouseEnter={() => handleMouseEnter(i)}
            onMouseLeave={() => handleMouseLeave(i)}
          >
            <div className="dossier-icon-wrapper">
              <critic.Icon size={24} className="dossier-icon" color="#a7a991" />
            </div>
            <div className="dossier-content">
              <h3>{critic.title}</h3>
              <p>{critic.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
