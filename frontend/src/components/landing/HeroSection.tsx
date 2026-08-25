import gsap from 'gsap';
import { ChevronRight } from 'lucide-react';
import { useLayoutEffect, useRef } from 'react';
import { Link } from 'react-router-dom';

export function HeroSection() {
  const containerRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    // prefers-reduced-motion fallback
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const ctx = gsap.context(() => {
      const tl = gsap.timeline();
      
      tl.fromTo('.hero-word', 
        { y: 30, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.8, stagger: 0.05, ease: 'power3.out' }
      )
      .fromTo(['.hero-sub', '.hero-cta', '.hero-visual'], 
        { y: 20, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.6, stagger: 0.1, ease: 'power2.out' },
        '-=0.4'
      );
    }, containerRef);
    
    return () => ctx.revert();
  }, []);

  const headline = "Send your product thesis into a room full of hostile specialists.";
  const words = headline.split(' ');

  return (
    <section className="hero-section" ref={containerRef}>
      <div className="hero-grid">
        <div className="hero-left">
          <h1>
            {words.map((word, i) => (
              <span key={i} className="hero-word-wrapper">
                <span className="hero-word">{word}&nbsp;</span>
              </span>
            ))}
          </h1>
        </div>
        <div className="hero-right">
          <p className="hero-sub">
            An AI-powered stress-testing platform. We route your raw ideas through a specialized panel of adversarial AI agents to identify vulnerabilities and synthesize a bulletproof specification.
          </p>
          <div className="hero-cta-wrapper">
            <Link to="/app" className="cta-btn primary hero-cta">
              Harden Your Spec Now <ChevronRight size={18} className="cta-icon" />
            </Link>
          </div>
          
          <div className="hero-visual">
            <div className="visual-terminal">
              <div className="visual-header">Live Signal</div>
              <div className="visual-body">
                <span className="cursor-blink">▌</span>
                <span>Connecting to Critics...</span><br/>
                <span className="log-success">SUCCESS</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
