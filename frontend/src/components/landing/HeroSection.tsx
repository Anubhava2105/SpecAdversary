import { Link } from 'react-router-dom';

/**
 * The examination: the spec on the stand, mid-cross-examination.
 * Transcript lines stamp in once via CSS, then stay. The copy below
 * demonstrates the mechanism with real critic names; it makes no
 * claims about customers, timings, or results.
 */
const LINES = [
  {
    no: '01',
    counsel: 'Assumption Hunter',
    speech: (
      <>
        You say users will pay. <strong>What has anyone actually paid for so far?</strong>
      </>
    ),
    stamp: null as { text: string; className: string } | null,
  },
  {
    no: '02',
    counsel: 'Competitor Simulator',
    speech: (
      <>
        We would ship the single-player version in a weekend <strong>and take your first ten users.</strong>
      </>
    ),
    stamp: { text: 'Admitted', className: 'admitted' },
  },
  {
    no: '03',
    counsel: 'Economics Tester',
    speech: (
      <>
        One model call per session, <strong>no cost per seat. Show the math.</strong>
      </>
    ),
    stamp: { text: 'Sustained', className: 'sustained' },
  },
];

export function HeroSection() {
  return (
    <section className="examination">
      <div className="examination-grid">
        <div>
          <p className="case-no">Case no. 0047 — hearing in progress</p>
          <h1>
            Send your product thesis into a room full of <span className="struck-word">hostile specialists.</span>
          </h1>
          <p className="examination-lede">
            SpecAdversary runs your spec past seven critics who try to break it. You get a
            revised spec and a list of risks to work through. No signup needed to start.
          </p>
          <div className="examination-cta-row">
            <Link to="/app" className="cta-btn primary">
              Put your spec on the stand
            </Link>
            <span className="no-signup">Guest sessions are free.</span>
          </div>
        </div>
        <div>
          <figure className="transcript" aria-label="Sample cross-examination transcript">
            <figcaption className="transcript-head">
              <span>Record of proceedings</span>
              <span className="exhibit-tag">Exhibit A</span>
            </figcaption>
            <div className="transcript-body">
              {LINES.map((line, i) => (
                <div
                  key={line.no}
                  className="transcript-line enter"
                  style={{ animationDelay: `${0.25 + i * 0.35}s` }}
                >
                  <span className="line-no" aria-hidden="true">{line.no}</span>
                  <span>
                    <span className="counsel">{line.counsel}</span>
                    <span className="speech">
                      {line.speech}
                      {line.stamp && (
                        <span className={`stamp ${line.stamp.className}`}>{line.stamp.text}</span>
                      )}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </figure>
        </div>
      </div>
    </section>
  );
}
