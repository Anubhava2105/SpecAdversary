import { useEffect, useLayoutEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { HeroSection } from '../components/landing/HeroSection';
import { DossierSection } from '../components/landing/DossierSection';
import { WorkflowSection } from '../components/landing/WorkflowSection';
import '../styles/landing.css';
import { GitBranch, FileText } from 'lucide-react';

gsap.registerPlugin(ScrollTrigger);

export function LandingPage() {
  const headerRef = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    let ctx = gsap.context(() => {
      // Frosted glass transition on scroll
      ScrollTrigger.create({
        start: 'top -50',
        end: 99999,
        toggleClass: { className: 'scrolled', targets: headerRef.current },
      });
    });
    return () => ctx.revert();
  }, []);

  return (
    <div className="landing-page">
      <header className="landing-nav" ref={headerRef}>
        <div className="nav-left">
          <Link to="/" className="logo">
            Spec<span className="logo-accent">Adversary</span>
          </Link>
        </div>
        <div className="nav-right">
          <a href="#features" className="nav-link">Features</a>
          <a href="#how-it-works" className="nav-link">How it Works</a>
          <a href="/docs" className="nav-link">Docs</a>
          <Link to="/app" className="cta-btn bordered">Launch App</Link>
        </div>
      </header>

      <main>
        <HeroSection />
        <DossierSection />
        <WorkflowSection />
        
        <section className="social-proof">
          <h2>Stop building the wrong thing.</h2>
          <p>Turn a 2-week review cycle into a 2-minute stress test.</p>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="footer-links">
          <a href="https://github.com"><GitBranch size={18} /> GitHub</a>
          <a href="/docs"><FileText size={18} /> Documentation</a>
          <a href="/privacy">Privacy Policy</a>
          <a href="/terms">Terms of Service</a>
        </div>
      </footer>
    </div>
  );
}
