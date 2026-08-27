/**
 * Step 1's channel — the session: what to open, and what came back.
 *
 * Connecting is not one action but a handful of questions, and the operator
 * needs to see the answers: an autofocus that fails an hour into a run
 * because the storage path was never writable is a bad way to find out. So
 * the card is two boxes. The first is what the session is opened with — the
 * microscope, its API, the password — and it locks once the session is open,
 * because everything after this was read through it. The second is what the
 * driver said when it opened: one row per check it reports, each waiting
 * until its answer arrives.
 *
 * The card reaches for nothing around it. What it shows and what it does
 * arrive in `ctx`; the handle it gives back is how a check's answer lands
 * in the row already on screen.
 */

import { sideGroup } from "../../../../framework/window/panels.js";
import { isFailed } from "../../../../parts/microscope/connection-status.js";

export function renderSessionCard(host, ctx) {
  const session = ctx.session();
  const connected = ctx.connected();
  let connectBtn = null;
  let connectHint = null;
  const connecting = ctx.connecting();
  /* The first step is headed the way every other step is: the name above the
     box, the box holding the work. What the session was opened with is
     already in the fields and in the rail beside them, so a third copy in the
     corner was the panel talking about itself. */
  const { group, body: card } = sideGroup("Connect to the microscope");
  card.classList.add("session-card");
  if (connected) card.classList.add("done");

  {
    const locked = connected || connecting;
    const form = document.createElement("div");
    form.className = "session-form";

    const scope = document.createElement("label");
    scope.className = "field";
    scope.innerHTML = "<span>Microscope</span><select></select>";
    const scopeSel = scope.querySelector("select");
    for (const m of ctx.instruments()) {
      const o = document.createElement("option");
      o.value = m.key;
      o.textContent = m.detail ? `${m.label} · ${m.detail}` : m.label;
      scopeSel.append(o);
    }
    if (!ctx.instruments().length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "no instruments listed";
      scopeSel.append(o);
    }
    scopeSel.value = session.microscope ?? "";
    scopeSel.disabled = locked || !ctx.instruments().length;
    scopeSel.addEventListener("change", () => {
      session.microscope = scopeSel.value;
      session.api = ctx.chosenMicroscope()?.apis[0]?.key ?? null;
      ctx.changed();
    });

    const api = document.createElement("label");
    api.className = "field";
    api.innerHTML = "<span>API</span><select></select>";
    const apiSel = api.querySelector("select");
    for (const a of ctx.chosenMicroscope()?.apis ?? []) {
      const o = document.createElement("option");
      o.value = a.key;
      o.textContent = a.detail ? `${a.label} · ${a.detail}` : a.label;
      apiSel.append(o);
    }
    apiSel.value = session.api ?? "";
    apiSel.disabled = locked || !ctx.chosenMicroscope();
    apiSel.addEventListener("change", () => {
      session.api = apiSel.value;
      ctx.changed();
    });

    const pw = document.createElement("label");
    pw.className = "field";
    pw.innerHTML = '<span>Password</span><input type="password" autocomplete="current-password">';
    const pwInput = pw.querySelector("input");
    pwInput.value = session.password;
    pwInput.disabled = locked;
    /* Typing must not rebuild the card: re-rendering destroys the very
       input being typed into, which drops focus after every keystroke.
       Only what depends on the password is touched. */
    pwInput.addEventListener("input", () => {
      session.password = pwInput.value;
      const ready = !!pwInput.value;
      if (connectBtn) connectBtn.disabled = connecting || !ready;
      if (connectHint) connectHint.hidden = ready;
    });

    form.append(scope, api, pw);
    card.append(form);
  }

  /* What the session was opened with is one thing; what came back when it
     was opened is another, so the answers stand in a box of their own under
     it. Every check is listed the moment the session is opened and each one
     ticks as its answer comes back — the row is the question, the mark is the
     answer. An open session is not editable, so the fields above stay on show
     as the record of what it was opened with. */
  let checks = null;
  const rows = [];
  if (ctx.checks().length) {
    const made = sideGroup("Connection checks");
    checks = made.body;
    /* Beside the session's box, not inside it: two boxes standing in the
       channel, the way every other step's boxes stand. */
    host.append(made.group);
    const list = document.createElement("div");
    list.className = "check-list";
    for (const c of ctx.checks()) {
      const answered = c.result !== null;
      const failed = answered && isFailed(c.result);
      const row = document.createElement("div");
      row.className = "check-row" + (answered ? "" : " pending") + (failed ? " failed" : "");
      row.innerHTML = '<span class="check-mark"></span><span class="check-name"></span>'
        + '<span class="check-value"></span>';
      row.querySelector(".check-mark").textContent = failed ? "✗" : "✓";
      row.querySelector(".check-name").textContent = c.label;
      row.querySelector(".check-value").textContent = answered ? c.result : "";
      rows.push(row);
      list.append(row);
    }
    checks.append(list);
  }

  /* The button sits at the end of the card, after everything it acts on —
     the rule every other step already follows. Once the session is open the
     press has nothing left to do, so what stands in its place is not a button
     at all: a green lamp and the word for it, the way an instrument says it is
     on. The way back out is the button, beside it. */
  {
    const foot = document.createElement("div");
    foot.className = "session-foot";
    const row = document.createElement("div");
    row.className = "session-buttons";

    if (connected) {
      const held = document.createElement("div");
      held.className = "session-state";
      held.innerHTML = '<i class="lamp"></i>';
      held.append("Connected");

      const out = document.createElement("button");
      out.type = "button";
      out.className = "danger";
      out.textContent = "Disconnect";
      out.disabled = !!ctx.running();
      out.addEventListener("click", () => ctx.disconnect());
      row.append(held, out);
    } else {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "run";
      btn.textContent = connecting ? "connecting…" : "Connect";
      btn.disabled = connecting || !session.password || !ctx.chosenConnection();
      btn.addEventListener("click", () => ctx.connect());
      connectBtn = btn;

      connectHint = document.createElement("div");
      connectHint.className = "session-hint";
      connectHint.textContent = "a password is needed to open the session";
      connectHint.hidden = !!session.password || connecting;
      row.append(btn);
    }

    foot.append(row);
    if (connectHint) foot.append(connectHint);
    card.append(foot);
  }

  host.prepend(group);

  /* Only the answer lands. The row is already on screen, so filling one in
     touches that row rather than rebuilding the card under the operator —
     which would restart every other row's arrival along with it. */
  return {
    answer(k, result) {
      const row = rows[k];
      if (!row) return;
      row.classList.remove("pending");
      row.classList.toggle("failed", isFailed(result));
      row.querySelector(".check-mark").textContent = isFailed(result) ? "✗" : "✓";
      row.querySelector(".check-value").textContent = result;
    },
  };
}
