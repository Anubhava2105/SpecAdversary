import { useEffect, useRef } from 'react';

/**
 * Scroll reveals for the landing record. One IntersectionObserver per hook
 * instance. Items that enter together share a short wave (60ms apart, capped
 * at 180ms) so motion reads as one gesture instead of a page-wide stagger.
 * The root margin triggers just before entry so motion is underway instead
 * of starting late. Elements render in their final state when
 * prefers-reduced-motion is set (no reveal at all).
 */
export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      root.querySelectorAll('.reveal').forEach((el) => {
        el.classList.add('revealed');
      });
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const entering = entries.filter((entry) => entry.isIntersecting);
        entering.forEach((entry, i) => {
          const el = entry.target as HTMLElement;
          el.style.transitionDelay = `${Math.min(i * 60, 180)}ms`;
          el.classList.add('revealed');
          observer.unobserve(el);
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px 10% 0px' },
    );
    root.querySelectorAll('.reveal').forEach((el) => {
      observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  return ref;
}
