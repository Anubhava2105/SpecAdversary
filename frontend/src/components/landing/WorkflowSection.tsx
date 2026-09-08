const ACTS = [
  {
    no: 'Act I',
    title: 'Input',
    body: 'Paste a spec or attach a file. The gatekeeper splits it into sections and picks the critics that fit.',
  },
  {
    no: 'Act II',
    title: 'Attack',
    body: 'Each critic reads and files findings as they land. Push back on anything you disagree with and the panel re-examines it.',
  },
  {
    no: 'Act III',
    title: 'Verdict',
    body: 'The moderator merges overlaps. You get a revised spec plus a risk list with owners and due dates.',
  },
];

/** The proceedings: three acts, no pinned scrub timelines. */
export function ProceedingsSection() {
  return (
    <section className="record-section" id="proceedings">
      <h2 className="reveal">How a hearing runs.</h2>
      <p className="section-standfirst reveal">
        Three acts, same order every time. You watch all of it live.
      </p>
      <div className="proceedings">
        {ACTS.map((act) => (
          <div key={act.title} className="act reveal">
            <span className="act-no">{act.no}</span>
            <h3>{act.title}</h3>
            <p>{act.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
