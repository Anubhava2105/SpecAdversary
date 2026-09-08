import { CRITICS } from '../../lib/critics';

/**
 * The programme: the seven-counsel lineup as an evening bill.
 * Same seven names and jobs as the app; examined acts strike through
 * once revealed. No cards, no icons, no new claims.
 */
export function ProgrammeSection() {
  return (
    <section className="record-section" id="panel">
      <h2 className="reveal">The panel.</h2>
      <p className="section-standfirst reveal">
        Seven specialists. Each reads your spec looking for a different way it fails.
      </p>
      <ul className="programme" aria-label="The seven critics">
        {CRITICS.map((critic, i) => (
          <li
            key={critic.id}
            className="programme-line examined reveal"
          >
            <span className="programme-no" aria-hidden="true">
              C-{String(i + 1).padStart(2, '0')}
            </span>
            <span className="programme-name">{critic.title}</span>
            <span className="programme-count">{critic.job}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
