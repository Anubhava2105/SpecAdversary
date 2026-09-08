import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ProgrammeSection } from '../components/landing/DossierSection';
import { HeroSection } from '../components/landing/HeroSection';
import { VerdictSection } from '../components/landing/VerdictSection';
import { ProceedingsSection } from '../components/landing/WorkflowSection';
import { useReveal } from '../lib/useReveal';
import '../styles/landing.css';

const REPO_URL = 'https://github.com/Anubhava2105/SpecAdversary';

export function LandingPage() {
  const rootRef = useReveal<HTMLDivElement>();

  useEffect(() => {
    const onScroll = () => {
      document.querySelector('.landing-nav')?.classList.toggle('scrolled', window.scrollY > 50);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className="landing-page" ref={rootRef}>
      <header className="landing-nav">
        <div className="nav-left">
          <Link to="/" className="logo">
            Spec<span className="logo-accent">Adversary</span>
          </Link>
        </div>
        <nav className="nav-right" aria-label="Primary">
          <a href="#panel" className="nav-link">Panel</a>
          <a href="#proceedings" className="nav-link">Proceedings</a>
          <a href="#verdict" className="nav-link">Verdict</a>
          <Link to="/app" className="cta-btn bordered">Launch App</Link>
        </nav>
      </header>

      <main>
        <HeroSection />
        <ProgrammeSection />
        <ProceedingsSection />
        <VerdictSection />
      </main>

      <div className="sticky-cta">
        <Link to="/app" className="cta-btn primary">
          Put your spec on the stand
        </Link>
      </div>

      <footer className="landing-footer">
        <div className="footer-links">
          <a href={REPO_URL}>GitHub</a>
          <span className="no-signup">Hear it from critics before customers do.</span>
        </div>
      </footer>
    </div>
  );
}
