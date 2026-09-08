import { Link } from 'react-router-dom';

/**
 * The verdict: what a finished hearing leaves behind. The revised-spec
 * excerpt below is demonstration copy showing the shape of the output;
 * it describes no real customer or result.
 */
export function VerdictSection() {
  return (
    <section className="record-section" id="verdict">
      <h2 className="reveal">Leave with fewer surprises.</h2>
      <p className="section-standfirst reveal">
        Every hearing ends with two things: a revised spec and a risk list that
        stays open until a human closes each item.
      </p>
      <div className="verdict-grid">
        <div className="verdict-page reveal">
          <span className="stamp sustained verdict-stamp">Entered</span>
          <h3>Revised spec</h3>
          <p className="file-line">Record of proceedings — excerpt</p>
          <ul>
            <li>
              <b>Willingness to pay gets a test first.</b> Five paid pilots before billing is built.
            </li>
            <li>
              <b>Launch narrows to one team.</b> The beachhead is a single support desk, not "support teams".
            </li>
            <li>
              <b>Model cost moves into pricing.</b> Per-session spend is now a line item, not a footnote.
            </li>
          </ul>
        </div>
        <div className="verdict-note reveal">
          <p>
            Findings that survive become risks with an owner, a validation plan, and a due
            date. Reply to any finding and the critic re-examines it without redoing the
            whole hearing.
          </p>
          <p>
            <Link to="/app" className="cta-btn primary">
              Put your spec on the stand
            </Link>
          </p>
          <p className="no-signup">The first hearing is free and needs no account.</p>
        </div>
      </div>
    </section>
  );
}
