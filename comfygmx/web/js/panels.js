/* Modals: environments, settings, file browser, workflow open/save, help. */
'use strict';

/* One row per GROMACS installation. The binary name matters as much as the
   path: an MPI build installs gmx_mpi and no gmx at all, so selecting an
   installation sets both. */
function gmxInstallList(report, settings, onPick) {
  const list = UI.el('div');
  const candidates = report.gmxrc_candidates || [];
  if (!candidates.length) {
    list.appendChild(UI.el('div', {
      class: 'hint',
      text: 'None found. Add the directory your build lives under in Settings → '
          + 'GROMACS search roots, or leave GMXRC blank to use whatever gmx is on PATH.',
    }));
    return list;
  }
  const active = (settings || {}).gmxrc || '';
  for (const candidate of candidates) {
    const binary = candidate.binaries[0] || 'gmx';
    const current = candidate.path === active;
    const row = UI.el('div', { class: 'fb-row' }, [
      UI.el('span', {}, [
        UI.el('div', {}, [
          UI.el('span', { class: `badge ${current ? 'ok' : ''}`,
                          text: candidate.version || 'version ?' }),
          ` ${candidate.binaries.join(', ') || 'no binary in bin/'}`,
          current ? ' — in use' : '',
        ]),
        UI.el('div', { class: 'fb-size', text: candidate.path }),
      ]),
      UI.el('button', {
        class: 'small', text: current ? 'Selected' : 'Use this',
        onclick: async () => {
          await API.saveSettings({ gmxrc: candidate.path, gmx_binary: binary });
          UI.toast(`GROMACS ${candidate.version || ''} selected (${binary})`, 'ok');
          if (onPick) onPick(candidate, binary);
        },
      }),
    ]);
    list.appendChild(row);
  }
  return list;
}

const Panels = {

  /* ------------------------------------------------------ first-run setup */
  /* One button, on a machine that has nothing.

     The three kinds of missing thing are not interchangeable and the dialog
     says which is which, because the difference decides who does the work:
     conda and the tools go into the user's home directory and are therefore a
     button; system packages need root and are therefore a line to paste into a
     terminal, where the password prompt has somewhere to appear. Offering a
     button that silently hangs on an invisible sudo prompt would be worse than
     offering no button at all. */
  async setup(auto = false, preselect = []) {
    const body = UI.el('div');
    const machine = UI.el('div', { class: 'hint', text: 'looking at this machine…' });
    const intro = UI.el('p', { class: 'hint', text:
      'Everything below goes into your home directory: conda into ~/miniforge3, then '
      + 'each tool into its own environment. Your shell startup files are left alone '
      + 'and nothing asks for your password.' });
    const reqBox = UI.el('div');
    const sudoBox = UI.el('div');
    const toolBox = UI.el('div');
    const notes = UI.el('div', { class: 'hint' });
    const preview = UI.el('pre', { text: 'working out what is needed…' });
    const output = UI.el('pre', { class: 'hidden' });
    const initShell = UI.el('input', { type: 'checkbox' });

    body.appendChild(machine);
    body.appendChild(intro);
    body.appendChild(reqBox);
    body.appendChild(sudoBox);
    body.appendChild(toolBox);
    body.appendChild(UI.el('div', { class: 'field' }, [
      UI.el('label', { class: 'check' }, [initShell, ' also add conda to my own shell startup']),
      UI.el('div', { class: 'hint', text:
        'Off by default: Comfy-gmx reaches this conda directly and does not need it on '
        + 'your PATH. Tick it if you want to type `conda activate` in your own terminal.' }),
    ]));
    body.appendChild(notes);
    body.appendChild(UI.el('h3', { text: 'What will run' }));
    body.appendChild(preview);
    body.appendChild(output);

    UI.modal('Set up this machine', body, [
      {
        label: auto ? 'Not now' : 'Close',
        action: () => { if (auto) API.setupDone().catch(() => {}); },
      },
      { label: 'Copy script', action: () => { UI.copy(preview.textContent); return false; } },
      { label: 'Set it up', primary: true, action: () => { install(); return false; } },
    ], { reopen: () => this.setup(auto, preselect) });
    const primary = document.querySelector('#modal-footer button.primary');
    if (primary) primary.disabled = true;

    let state = null;
    let plan = null;
    const checkboxes = new Map();

    const choices = () => ({
      tools: [...checkboxes.entries()].filter(([, box]) => box.checked).map(([id]) => id),
      init_shell: initShell.checked,
      // A tick is an instruction, not a suggestion: install it even if the
      // files look like they are already there. They may be there and broken.
      force: true,
    });

    let pending = 0;
    const replan = async () => {
      // Two clicks in quick succession are two requests in flight, and the
      // slower answer must not paint over the newer one.
      const mine = ++pending;
      try {
        const fresh = await API.setupPlan(choices());
        if (mine !== pending) return;
        plan = fresh;
        preview.textContent = fresh.script || '# nothing to install';
        notes.innerHTML = '';
        for (const note of fresh.notes || []) {
          notes.appendChild(UI.el('div', { class: 'warned', text: `• ${note}` }));
        }
        renderSudo(fresh.sudo_commands || []);
        if (primary) {
          primary.disabled = !(fresh.steps || []).length;
          primary.textContent = (fresh.steps || []).length
            ? `Install ${fresh.steps.length} thing${fresh.steps.length === 1 ? '' : 's'}`
            : 'Nothing to install';
        }
      } catch (err) {
        preview.textContent = err.message;
        plan = null;
      }
    };

    const renderSudo = (commands) => {
      sudoBox.innerHTML = '';
      if (!commands.length) return;
      sudoBox.appendChild(UI.el('h3', { text: 'Needs your password — run this yourself' }));
      sudoBox.appendChild(UI.el('p', { class: 'hint', text:
        'These are system packages, so they need root. A browser button cannot ask for '
        + 'a password, so here it is for a terminal where the prompt is visible.' }));
      for (const entry of commands) {
        const line = UI.el('code', { text: entry.command });
        sudoBox.appendChild(UI.el('div', { class: 'row' }, [
          line,
          UI.el('button', { class: 'small', text: 'Copy',
            onclick: () => UI.copy(entry.command) }),
        ]));
        sudoBox.appendChild(UI.el('div', { class: 'hint',
          text: `${entry.name}: ${entry.why}` }));
      }
    };

    const install = () => {
      if (!plan || !(plan.steps || []).length) {
        UI.toast('nothing to install', 'warn');
        return;
      }
      output.classList.remove('hidden');
      output.textContent = '';
      if (primary) primary.disabled = true;
      API.setupRun(choices()).then((job) => {
        UI.toast(`installing ${job.steps.length} thing(s) — the terminal has the log too`,
          'info', 9000);
        Terminal.say(`setting up: ${job.steps.map((s) => s.name).join(', ')}`,
                     'setup', 'head');
        this.watchJob(job.job, output, 'setup');
        API.stream(`api/jobs/${job.job}/events`, (event) => {
          if (event.line !== undefined) {
            this.appendOutput(output, event);
            if (!event.replace) Terminal.say(event.line, 'setup');
          }
          if (event.status === 'done') {
            UI.toast('setup finished — the tools are registered and ready', 'ok', 12000);
            API.setupDone().catch(() => {});
            App.refreshEnvInfo();
            // Deliberately not reopening the dialog: the log the user is
            // reading is the most useful thing on the screen at that moment.
            if (primary) {
              primary.textContent = 'Done';
              primary.disabled = true;
            }
            notes.innerHTML = '';
            notes.appendChild(UI.el('div', { class: 'ok-line', text:
              'Installed and registered. Close this and the tools are already '
              + 'selected in the Environments panel.' }));
          } else if (event.status === 'error') {
            UI.toast('some steps did not finish — the log is above, and each step is a '
              + `script in ${job.workdir} you can re-run by hand`, 'error', 15000);
            if (primary) primary.disabled = false;
          } else if (event.status === 'cancelled') {
            if (primary) primary.disabled = false;
          }
        });
      }).catch((err) => {
        UI.toast(err.message, 'error', 12000);
        if (primary) primary.disabled = false;
      });
    };

    try {
      state = await API.setup();
    } catch (err) {
      machine.textContent = `could not look at this machine: ${err.message}`;
      return;
    }

    const plat = state.platform;
    const bits = [plat.pretty];
    if (plat.family) bits.push(plat.manager ? `${plat.family} · ${plat.manager}` : plat.family);
    bits.push(plat.machine, `Python ${plat.python}`);
    if (plat.wsl) bits.push('WSL');
    machine.textContent = bits.join(' · ');

    if (!plat.supported) {
      intro.textContent = `${plat.system} is not supported natively. On Windows, install `
        + 'WSL2 and run Comfy-gmx inside it, where it is simply Linux.';
      preview.textContent = '';
      return;
    }

    // What is here already, and what is not.
    const reqTable = UI.el('table');
    for (const req of state.requirements) {
      reqTable.appendChild(UI.el('tr', {}, [
        UI.el('td', {}, [UI.el('span', {
          class: `badge ${req.present ? 'ok' : (req.essential ? 'missing' : '')}`,
          text: req.present ? 'here' : (req.essential ? 'needed' : 'optional'),
        })]),
        UI.el('td', {}, [
          UI.el('div', { text: req.name }),
          UI.el('div', { class: 'hint', text: req.present ? req.detail : req.why }),
        ]),
      ]));
    }
    reqBox.appendChild(UI.el('h3', { text: 'This machine' }));
    reqBox.appendChild(reqTable);

    // The tools. Ticked ones get installed; the rest stay available for later.
    toolBox.appendChild(UI.el('h3', { text: 'Tools' }));
    toolBox.appendChild(UI.el('p', { class: 'hint', text:
      'Nothing is ticked: the two tutorials need only GROMACS and Python. Anything '
      + 'here can be installed later from the Environments panel, one click each. '
      + 'GROMACS is separate: it is built from source, which is its own dialog '
      + 'because the flags matter.' }));
    const wanted = new Set(preselect || []);

    /* Not everything is a checkbox. GROMACS has no conda route -- one build
       with the choices already baked in is how you end up running the wrong
       gmx for a week -- so it gets a button through to the builder, where the
       version and the flags are chosen. */
    const buildRow = (tool) => UI.el('div', { class: 'row' }, [
      UI.el('span', { text: tool.name }),
      UI.el('button', {
        class: 'small primary', text: 'Build from source…',
        title: tool.install_hint || '',
        onclick: () => this.gromacs(),
      }),
      UI.el('span', { class: 'hint', text: tool.install_hint || '' }),
    ]);

    const row = (tool) => {
      if (tool.conda_installable === false) return buildRow(tool);
      const box = UI.el('input', { type: 'checkbox' });
      box.checked = wanted.has(tool.id) || (!tool.present && Boolean(tool.default));
      box.addEventListener('change', replan);
      checkboxes.set(tool.id, box);
      const label = UI.el('label', {
        class: 'check',
        title: tool.present
          ? `${tool.description}\n\nfound at ${tool.where} — tick to install it again`
          : tool.description,
      }, [box, ` ${tool.name}${tool.licence_key ? ' (needs a key)' : ''}`]);
      label.style.minWidth = '210px';
      if (tool.present) label.style.color = 'var(--text-dim)';
      return label;
    };

    const missing = state.tools.filter((tool) => !tool.present);
    const here = state.tools.filter((tool) => tool.present);

    const grid = UI.el('div', { class: 'row wrap' });
    for (const tool of missing) grid.appendChild(row(tool));
    if (!missing.length) {
      grid.appendChild(UI.el('div', { class: 'hint',
        text: 'Every tool in the catalogue is already installed.' }));
    }
    toolBox.appendChild(grid);

    if (here.length) {
      toolBox.appendChild(UI.el('h3', { text: 'Already installed' }));
      toolBox.appendChild(UI.el('p', { class: 'hint', text:
        'Tick one to install it again. Worth doing if an install failed partway: '
        + 'the files it left behind are enough to make it look present here, which is '
        + 'not the same as working.' }));
      const done = UI.el('div', { class: 'row wrap' });
      for (const tool of here) done.appendChild(row(tool));
      toolBox.appendChild(done);
      const where = UI.el('div', { class: 'hint', text:
        here.map((tool) => `${tool.name} — ${tool.where}`).join(' · ') });
      where.style.marginTop = '8px';
      toolBox.appendChild(where);
    }
    initShell.addEventListener('change', replan);
    replan();
  },


  /* What is missing, and every way of getting it that would work here.

     Shared, because the answer has the same shape whether it is cmake before a
     build or git before a pip-from-a-repository install: name what is absent,
     say where a copy is hiding if one is, and then only the routes that hold on
     this machine -- a pip line on a distribution that ships no pip is advice
     whose one outcome is an error message. */
  requirementPanel(container, kit, subject) {
    const missing = (kit && kit.missing) || [];
    if (!missing.length) return;
    container.appendChild(UI.el('p', { class: 'warned', text:
      `This machine cannot ${subject} yet — ${missing.join(', ')} not on PATH.` }));

    const line = (text) => UI.el('div', { class: 'row' }, [
      UI.el('code', { text }),
      UI.el('button', { class: 'small', text: 'Copy', onclick: () => UI.copy(text) }),
    ]);

    // "Not on PATH" and "not installed" are different problems with different
    // answers. Something in an environment nobody activated fails identically
    // to nothing at all, and being told to install what you have is no answer.
    for (const found of kit.elsewhere || []) {
      container.appendChild(UI.el('p', { class: 'hint', text:
        `There is a ${found.command} in the conda environment ${found.env}, at `
        + `${found.path}. Nothing here activates an environment, so it is not seen. `
        + 'Either install one properly, or start the server from a shell with that '
        + 'environment active.' }));
    }

    for (const route of kit.routes || []) {
      container.appendChild(UI.el('p', { class: 'hint', text:
        `${route.label}. ${route.note}` }));
      if (route.command) container.appendChild(line(route.command));
      if (route.kind === 'setup') {
        container.appendChild(UI.el('button', {
          class: 'small primary', text: 'Set up this machine…',
          onclick: () => this.setup(false),
        }));
      }
    }
    if (!(kit.routes || []).length) {
      container.appendChild(UI.el('p', { class: 'hint', text:
        'Install it with whatever this system uses.' }));
    }
    container.appendChild(UI.el('p', { class: 'hint', text:
      'Then reopen this dialog — it re-checks each time.' }));
  },

  /* One place that puts a job's output on screen.

     A progress bar repainting itself arrives with replace set, and overwrites
     the last line instead of following it -- otherwise a conda solve writes a
     few hundred near-identical lines, the real output scrolls away, and the
     panel looks like it is losing pieces of itself. Which it was: past 5000
     lines the server drops the oldest thousand.

     Also caps what the element holds. A long build is tens of thousands of
     lines and a <pre> that big makes the whole dialog crawl. */
  appendOutput(output, event, follow = true) {
    const line = `${event.line}\n`;
    if (event.replace && output.dataset.replaceable === '1') {
      const text = output.textContent;
      const cut = text.lastIndexOf('\n', text.length - 2);
      output.textContent = (cut < 0 ? '' : text.slice(0, cut + 1)) + line;
    } else {
      output.textContent += line;
    }
    output.dataset.replaceable = event.replace ? '1' : '0';
    if (output.textContent.length > 400000) {
      output.textContent = output.textContent.slice(-300000);
    }
    if (follow) output.scrollTop = output.scrollHeight;
  },

  /* Nothing runs without GROMACS, so say so on the way in.

     It is not part of first-run setup -- a source build is forty minutes and
     the flags matter, so it belongs in its own dialog -- which means somebody
     could otherwise get a working editor, build a graph, press Run and only
     then find out. This is the reminder, once per browser session, with both
     ways to fix it on it. The Set up button in the toolbar is the version that
     does not go away. */
  needGromacs(force = false, andThen = null, found = []) {
    if (!force && sessionStorage.getItem('comfygmx-gromacs-notice') === 'seen') {
      if (andThen) andThen();
      return;
    }
    sessionStorage.setItem('comfygmx-gromacs-notice', 'seen');

    // Builds on disk that no run would use: no GMXRC chosen in Settings, and
    // no gmx on the command path. "Not installed" would be untrue there, and
    // the list is what Settings should be pointed at.
    const onDisk = (found || []).length > 0;
    const body = UI.el('div', {}, [
      onDisk
        ? UI.el('p', { text:
          'GROMACS is on this machine, but a run would not find it: Settings name no '
          + 'GMXRC that works, and there is no gmx on the command path. Nothing in a '
          + 'graph will run until one is chosen. Found here:' })
        : UI.el('p', { text:
          'No GROMACS was found, and nothing in a graph will run without it. '
          + 'Everything else works — you can build and check a graph now and get it '
          + 'later.' }),
      onDisk
        ? UI.el('ul', {}, found.map((build) =>
          UI.el('li', { text: `${build.version || '?'}   ${build.path}` })))
        : null,
      UI.el('h3', { text: 'Two ways to get it' }),
      UI.el('p', {}, [
        UI.el('b', { text: 'Build it from source. ' }),
        'Takes the better part of an hour. It asks for the version and the flags '
        + 'that matter — GPU backend, MPI, the SIMD level for this machine — and '
        + 'registers what it produces, so nothing else needs configuring afterwards.',
      ]),
      UI.el('p', {}, [
        UI.el('b', { text: 'Point at one you already have. ' }),
        'A cluster module, a system package, an old build in your home directory: '
        + 'Settings takes the path to its GMXRC and finds the rest.',
      ]),
      UI.el('p', { class: 'hint', text:
        'There is no conda option on purpose. That package is one build with the '
        + 'choices already made — no GPU, no MPI, SIMD for whatever machine built '
        + 'it — and a second gmx on your PATH is a good way to run the wrong one '
        + 'for a week without noticing.' }),
    ]);

    UI.modal(onDisk ? 'GROMACS is not in use' : 'GROMACS is not installed', body, [
      // On a genuine first run there is usually setup to do as well; putting it
      // behind "Later" keeps the two from stacking on top of each other.
      { label: 'Later', action: () => { if (andThen) setTimeout(andThen, 0); } },
      {
        label: 'Point at an existing install…',
        action: () => { this.settings(); return false; },
      },
      {
        label: 'Build from source…', primary: true,
        action: () => { this.gromacs(); return false; },
      },
    ], { reopen: () => this.needGromacs(true, null, found) });
  },

  /* Point a repo-backed tool at a checkout the user maintains.

     The alternative people reach for is a symlink at the managed path, which
     works until something replaces it -- and then the tool silently goes back
     to the stock copy with nothing said anywhere. A recorded path cannot be
     overwritten by an installer, is checked when it is entered rather than at
     run time, and shows up on the row that claims the tool is installed. */
  async checkout(tool) {
    let state;
    try {
      state = await API.source(tool.id);
    } catch (err) {
      UI.toast(`could not read the checkout: ${err.message}`, 'warn', 6000);
      return;
    }
    const input = UI.el('input', {
      type: 'text', value: state.override || '',
      placeholder: state.default,
    });
    input.style.width = '100%';
    const status = UI.el('div', { class: 'hint' });
    status.style.marginTop = '6px';

    const body = UI.el('div', {}, [
      UI.el('p', {
        class: 'hint',
        text: `${tool.name} is a checkout rather than a package, so there is a `
          + 'directory on this machine that is the program. Leave this blank and '
          + `Comfy-gmx keeps its own at ${state.default}: installing clones there, `
          + 'updates there, and may replace it. Give a path and that one is run '
          + 'instead — your fork, or a clone you are editing — and the installer '
          + 'will only build the conda environment around it.',
      }),
      UI.el('label', { text: 'Directory' }),
      input,
      UI.el('p', {
        class: 'hint',
        text: state.marker
          ? `Checked when you save: it must exist and contain ${state.marker}.`
          : 'Checked when you save: it must exist.',
      }),
      status,
    ]);

    const apply = async (path) => {
      status.textContent = 'checking…';
      try {
        const result = await API.setSource(tool.id, path);
        const probe = result.probe || {};
        // The forgotten count matters: a build that was cached against the old
        // checkout will now run again, which is a wait the user should expect
        // rather than discover.
        const forgot = result.forgot
          ? ` — ${result.forgot} cached result${result.forgot === 1 ? '' : 's'} `
            + 'dropped, those nodes will run again'
          : '';
        UI.toast(`${tool.name}: now running ${result.override || result.path}`
          + (probe.found ? ` — ${probe.version}` : ` — ${probe.error || 'not usable yet'}`)
          + forgot,
          probe.found ? 'ok' : 'warn', 9000);
        // Closed rather than layered: the environments panel behind this one
        // is now out of date, and re-rendering it leaves a back arrow to a
        // dialog whose question has been answered.
        UI.closeModal();
        this.environments();
        return true;
      } catch (err) {
        status.textContent = err.message;
        status.style.color = 'var(--warn)';
        return false;
      }
    };

    UI.modal(`Which ${tool.name} checkout`, body, [
      { label: 'Cancel' },
      {
        label: 'Use the managed one',
        action: () => { apply(''); return false; },
      },
      {
        label: 'Save', primary: true,
        action: () => { apply(input.value.trim()); return false; },
      },
    ], { reopen: () => this.checkout(tool) });
  },

  /* The workflow as a folder of shell scripts, with the files it reads.

     What this is for: preparation, minimisation and equilibration here;
     production somewhere with a queue. The commands are the same ones this
     editor would run, but the staging Comfy-gmx does in Python is written out
     as shell, the inputs travel in `inputs/`, and every path that belongs to
     this machine is lifted into one `env.sh` to edit on arrival. */
  async exportScripts() {
    const selected = Editor.selected ? Editor.selected() : [];
    const dest = UI.el('input', { type: 'text',
      placeholder: '/scratch/…/my-production' });
    const label = UI.el('input', { type: 'text',
      value: App.workflowName || 'workflow' });
    // Set as properties, not attributes. UI.el turns every other key into
    // setAttribute, and `checked="false"` is still checked in HTML -- which
    // ticked the boxes this asked to leave clear, and selected the scope this
    // asked not to select.
    const wholeGraph = UI.el('input', { type: 'radio', name: 'exp-scope' });
    const justPicked = UI.el('input', { type: 'radio', name: 'exp-scope' });
    wholeGraph.checked = !selected.length;
    justPicked.checked = !!selected.length;
    justPicked.disabled = !selected.length;
    const withInputs = UI.el('input', { type: 'checkbox' });
    const withSlurm = UI.el('input', { type: 'checkbox' });
    withInputs.checked = true;
    withSlurm.checked = false;
    const partition = UI.el('input', { type: 'text', placeholder: 'queue name' });
    const walltime = UI.el('input', { type: 'text', value: '02:00:00' });
    const once = UI.el('input', { type: 'radio', name: 'exp-slurm' });
    const chained = UI.el('input', { type: 'radio', name: 'exp-slurm' });
    once.checked = true;
    const cpus = UI.el('input', { type: 'number', value: '8', min: '1' });
    const gpus = UI.el('input', { type: 'text', placeholder: 'no GPU' });
    const status = UI.el('div', { class: 'hint' });
    status.style.marginTop = '8px';

    const field = (labelText, control, hint) => UI.el('div', { class: 'field' }, [
      UI.el('label', { text: labelText }), control,
      hint ? UI.el('div', { class: 'hint', text: hint }) : null,
    ].filter(Boolean));

    // A choice and the sentence that explains it, kept together. One
    // paragraph covering both options makes the reader work out which half
    // applies to which button.
    const choice = (control, labelText, hint) => UI.el('div', { class: 'choice' }, [
      UI.el('label', { class: 'check' }, [control, labelText]),
      hint ? UI.el('div', { class: 'hint', text: hint }) : null,
    ].filter(Boolean));

    // Only shown when there is a submission to configure. Four boxes for a
    // file nobody asked for is four boxes of noise.
    const chainNote = UI.el('div', { class: 'hint' });
    const paintChain = () => {
      chainNote.textContent = chained.checked
        ? `The simulation runs for ${walltime.value.trim() || 'the time above'}, `
          + 'saves its place just before the time runs out, then puts itself '
          + 'back in the queue to carry on. It repeats until the simulation '
          + 'finishes — and stops early if it crashes, or if its log shows '
          + 'the structure came apart. Only works if the workflow ends in a '
          + 'simulation; there is nothing to carry on from otherwise.'
        : 'Goes into the queue once. If the work is not done by the time you '
          + 'asked for, it is stopped there and then.';
    };
    once.addEventListener('change', paintChain);
    chained.addEventListener('change', paintChain);
    walltime.addEventListener('input', paintChain);
    paintChain();

    const slurmRow = UI.el('div', { class: 'hidden' }, [
      UI.el('div', { class: 'row' }, [partition, walltime, cpus, gpus]),
      UI.el('div', { class: 'hint', text:
        'Which queue · how long you are asking for · how many processors · '
        + 'how many GPUs. Leave anything you do not know yet. The file that '
        + 'comes out explains every line in plain words, and carries the '
        + 'commands that ask the cluster the rest — including one that checks '
        + 'the file without actually submitting it.' }),
      UI.el('label', { class: 'check' }, [once, ' put it in the queue once']),
      UI.el('label', { class: 'check' }, [chained,
        ' keep going in turns until the simulation finishes']),
      chainNote,
    ]);
    slurmRow.style.marginLeft = '19px';
    withSlurm.addEventListener('change', () => {
      slurmRow.classList.toggle('hidden', !withSlurm.checked);
    });

    const body = UI.el('div', {}, [
      UI.el('p', { class: 'hint', text:
        'Writes a folder holding one directory per step, each with its own '
        + 'command.sh, plus a run_all.sh that runs them in order. Nothing in '
        + 'it needs Comfy-gmx.' }),
      field('Write it to', dest, 'must not exist, or must be empty'),
      field('Called', label),

      UI.el('div', { class: 'field-label', text: 'how much of it' }),
      choice(wholeGraph, ' the whole workflow',
        `all ${Editor.nodes.size} node(s), with everything they read`),
      choice(justPicked,
        selected.length
          ? ` just the ${selected.length} node(s) selected on the canvas`
          : ' just the selected nodes',
        selected.length
          ? 'What they read from the rest has to have been produced already — '
            + 'that is what makes "prepare here, run there" work. If it has '
            + 'not been, the export says which node to run rather than '
            + 'writing something that fails on arrival.'
          : 'Nothing is selected. Close this, select the nodes you want, and '
            + 'open it again.'),

      UI.el('div', { class: 'field-label', text: 'what travels with it' }),
      choice(withInputs, ' copy the input files in',
        'Off writes inputs/MANIFEST.txt listing what to bring instead — for '
        + 'when the inputs are large and you would rather rsync them yourself.'),
      choice(withSlurm, ' also write a submit.sbatch'),
      slurmRow,

      status,
    ]);

    UI.modal('Export as scripts', body, [
      { label: 'Cancel' },
      {
        label: 'Export', primary: true,
        action: () => {
          const where = dest.value.trim();
          if (!where) { status.textContent = 'where should it go?'; return false; }
          status.textContent = 'writing…';
          status.style.color = '';
          API.exportScripts(Editor.toJSON(), {
            dest: where,
            nodes: justPicked.checked ? selected : null,
            label: label.value.trim(),
            copy_inputs: withInputs.checked,
            slurm: withSlurm.checked ? {
              partition: partition.value.trim(),
              time: walltime.value.trim(),
              cpus: Number(cpus.value) || 8,
              gpus: gpus.value.trim(),
              mode: chained.checked ? 'chain' : 'once',
            } : null,
          }).then((result) => {
            UI.closeModal();
            const files = result.inputs.length
              ? `, ${result.inputs.length} input file(s)` : '';
            const chain = result.chain
              ? ` — submit.sbatch chains ${result.chain.step} and stops when `
                + `${result.chain.prefix}.gro appears`
              : '';
            UI.toast(`${result.steps.length} step(s)${files} written to ${result.path}`
              + ' — check env.sh before running' + chain, 'ok', 10000);
          }).catch((err) => {
            status.textContent = err.message;
            status.style.color = 'var(--warn)';
          });
          return false;
        },
      },
    ], { reopen: () => this.exportScripts() });
  },

  /* ------------------------------------------------------- environments */
  async environments() {
    const body = UI.el('div');
    body.appendChild(UI.el('p', {
      class: 'hint',
      text: 'Point each tool at an installation you already have, or let Comfy-gmx '
          + 'build a conda environment for it. Nothing is installed without you asking.',
    }));
    const table = UI.el('div', { text: 'probing tools…' });
    body.appendChild(table);
    UI.modal('Software & environments', body, [
      { label: 'Close' },
      {
        label: 'Set up this machine…',
        action: () => { this.setup(false); return false; },
      },
      {
        // Not folded into the survey above: a conda search is twenty seconds a
        // package, and paying it on every visit would make this dialog feel
        // broken. Asked for explicitly, twenty seconds is fine.
        label: 'Check for updates',
        action: () => { this.checkUpdates(); return false; },
      },
    ], { reopen: () => this.environments() });

    let report;
    try {
      report = await API.environment(true);
    } catch (err) {
      table.textContent = `could not read the environment: ${err.message}`;
      return;
    }
    this._report = report;
    table.innerHTML = '';

    const summary = UI.el('table');
    summary.appendChild(UI.el('tr', {}, [
      UI.el('th', { text: 'Tool' }), UI.el('th', { text: 'Status' }),
      UI.el('th', { text: 'Environment' }), UI.el('th', { text: '' }),
    ]));

    for (const tool of report.tools || []) {
      const badge = UI.el('span', {
        class: `badge ${tool.found ? 'ok' : 'missing'}`,
        text: tool.found ? 'found' : 'missing',
      });
      const detail = UI.el('div', {
        class: 'hint',
        text: tool.found ? tool.version : (tool.error || ''),
      });
      const advice = UI.el('div', {
        class: 'hint',
        text: tool.found ? '' : (tool.troubleshooting || ''),
      });
      advice.style.marginTop = '4px';
      advice.style.color = 'var(--warn)';

      // A list of what is actually installed, not a box to remember a name in.
      // Several versions can sit side by side, and switching between them
      // should be one click rather than typing an environment name correctly.
      const found = (report.installs || {})[tool.id] || [];
      const listId = `envs-${tool.id}`;
      const envInput = UI.el('input', {
        type: 'text', value: tool.env || '', list: listId,
        placeholder: tool.suggested_env || 'system PATH',
        title: 'conda environment to activate for this tool',
      });
      const datalist = UI.el('datalist', { id: listId });
      for (const install of found) {
        datalist.appendChild(UI.el('option', {
          value: install.env,
          label: install.version || install.guess || '',
        }));
      }
      const others = UI.el('div', { class: 'hint' });
      const describeInstalls = () => {
        others.innerHTML = '';
        if (found.length < 2) return;
        others.appendChild(UI.el('span', { text: `${found.length} installs: ` }));
        for (const install of found) {
          const label = `${install.env}${install.version || install.guess
            ? ` (${install.version || install.guess})` : ''}`;
          if (install.env === envInput.value.trim()) {
            others.appendChild(UI.el('b', { text: `${label} ` }));
            continue;
          }
          others.appendChild(UI.el('button', {
            class: 'small link', text: label,
            title: `use ${install.env} for this tool from now on`,
            onclick: () => { envInput.value = install.env; use(install.env); },
          }));
          others.appendChild(document.createTextNode(' '));
        }
      };
      const use = async (name) => {
        const result = await API.useInstall(tool.id, name);
        for (const install of found) install.active = install.env === name;
        describeInstalls();
        const probe = result.probe || {};
        detail.textContent = probe.found ? probe.version : (probe.error || '');
        badge.className = `badge ${probe.found ? 'ok' : 'missing'}`;
        badge.textContent = probe.found ? 'found' : 'missing';
        UI.toast(`${tool.name}: now using ${name || 'whatever is on PATH'}`
          + (probe.found ? ` — ${probe.version}` : ''), probe.found ? 'ok' : 'warn', 7000);
      };
      envInput.addEventListener('change', () => use(envInput.value.trim()));

      // Some tools are a checkout rather than a package, and that checkout can
      // be one the user maintains -- a fork, or a clone they are editing. It
      // is worth showing on the row that claims the tool is installed, because
      // "installed" alone does not say *which* copy is being run.
      const where = UI.el('div', { class: 'hint' });
      const paintWhere = () => {
        where.innerHTML = '';
        if (!tool.repo) return;
        const mine = !!tool.source_override;
        where.appendChild(UI.el('div', {
          text: `${mine ? 'your checkout' : 'checkout'}: ${tool.source}`,
          title: mine
            ? 'you maintain this one; installing only builds the environment around it'
            : 'the installer owns this one and may clone, pull or replace it',
        }));
        where.appendChild(UI.el('button', {
          class: 'small link',
          text: mine ? 'change or reset…' : 'use my own checkout…',
          onclick: () => this.checkout(tool),
        }));
      };
      paintWhere();

      const actions = UI.el('div', { class: 'row' }, [
        UI.el('button', {
          class: 'small', text: 'Test',
          onclick: async () => {
            const result = await API.probe(tool.id);
            UI.toast(`${tool.name}: ${result.found ? result.version : (result.error || 'missing')}`,
              result.found ? 'ok' : 'warn', 6000);
            detail.textContent = result.found ? result.version : (result.error || '');
            advice.textContent = result.found ? '' : (result.troubleshooting || '');
            badge.className = `badge ${result.found ? 'ok' : 'missing'}`;
            badge.textContent = result.found ? 'found' : 'missing';
          },
        }),
        tool.conda_installable === false
          ? UI.el('button', {
            class: 'small', text: 'Build from source…',
            title: tool.install_hint || 'this one is built, not installed into an environment',
            onclick: () => this.gromacs(),
          })
          : UI.el('button', {
            class: 'small', text: 'Install',
            title: 'create or update a conda environment containing this tool',
            onclick: () => this.install(tool),
          }),
      ].filter(Boolean));

      summary.appendChild(UI.el('tr', {}, [
        UI.el('td', {}, [
          UI.el('div', { text: tool.name }),
          UI.el('div', { class: 'hint', text: tool.description }),
          tool.notes ? UI.el('div', { class: 'hint', text: `note: ${tool.notes}` }) : null,
        ]),
        UI.el('td', {}, [badge, detail, advice]),
        UI.el('td', {}, [envInput, datalist, others, where]),
        UI.el('td', {}, [actions]),
      ]));
      describeInstalls();
    }
    table.appendChild(summary);

    table.appendChild(UI.el('h3', { text: 'System' }));
    const system = UI.el('table');
    const rows = [
      ['conda root', report.conda_root || '(not found)'],
      ['data directory', report.data_dir],
      ['locale', Object.entries(report.locale || {}).map(([k, v]) => `${k}=${v || '?'}`).join('  ')],
    ];
    if (report.disk && report.disk.free) {
      rows.push(['disk free', UI.bytes(report.disk.free)]);
    }
    // What it is using, and where. Free space alone does not tell you that two
    // abandoned build trees are sitting in installs/ -- 1.8 GB went unnoticed
    // here until somebody went looking.
    const usage = (report.usage || []).filter((row) => row.bytes > 0);
    if (usage.length) {
      const total = usage.reduce((sum, row) => sum + row.bytes, 0);
      rows.push(['using', `${UI.bytes(total)} — `
        + usage.slice(0, 5).map((row) => `${row.name} ${UI.bytes(row.bytes)}`
          + (row.entries ? ` (${row.entries})` : '')).join(', ')
        + (usage.some((row) => row.partial) ? ' — still counting' : '')]);
    }
    for (const [key, value] of rows) {
      system.appendChild(UI.el('tr', {}, [
        UI.el('th', { text: key }), UI.el('td', { text: String(value) }),
      ]));
    }
    table.appendChild(system);

    table.appendChild(UI.el('h3', { text: 'Node cache' }));
    table.appendChild(this.cacheBlock());

    table.appendChild(UI.el('h3', { text: 'Conda environments' }));
    table.appendChild(this.envList(report));

    const gmxHead = UI.el('div', { class: 'row' }, [
      UI.el('h3', { text: 'GROMACS installations found' }),
      UI.el('span', { class: 'spacer' }),
      UI.el('button', {
        class: 'small', text: 'Build from source…',
        title: 'choose the version and the flags -- GPU, MPI, SIMD',
        onclick: () => this.gromacs(),
      }),
    ]);
    table.appendChild(gmxHead);
    table.appendChild(gmxInstallList(report, report.settings));

    table.appendChild(UI.el('h3', { text: 'Force fields' }));
    table.appendChild(this.forcefieldBlock());
  },

  /* ------------------------------------------------------- force fields */
  /* What the topology block can offer, and a way to add to it.

     GROMACS ships seventeen force fields and none of them is CHARMM36, which
     is what most membrane and protein work actually uses. Getting it used to
     mean finding the maintainers' download page, working out which of a dozen
     dated builds you wanted, unpacking a tarball, and knowing that it had to
     land in one particular folder for the topology block to list it. Four
     chores, none of them interesting, before you could pick a name from a
     list.

     So the list is here, next to everything else that gets installed, and one
     click does the fetching and the unpacking and puts it where GROMACS looks.
     The topology block's Force field box then has it, without a reload. */
  forcefieldBlock() {
    const wrap = UI.el('div');
    const status = UI.el('div', { class: 'hint', text: 'reading the folder…' });
    wrap.appendChild(status);
    const mine = UI.el('div');
    const shop = UI.el('div');
    wrap.appendChild(mine);
    wrap.appendChild(shop);

    const paint = async () => {
      let data;
      try {
        data = await API.forcefields();
      } catch (err) {
        status.textContent = `could not read the force fields: ${err.message}`;
        return;
      }
      this._forcefields = data;
      const yours = data.installed.filter((row) => row.where === 'yours');
      const gmx = data.installed.filter((row) => row.where !== 'yours');
      status.innerHTML = '';
      status.appendChild(UI.el('div', { text:
        `${data.installed.length} force field(s) on this machine, and the `
        + 'Topology (pdb2gmx) block lists every one of them. '
        + `${gmx.length} came with GROMACS; ${yours.length} `
        + `${yours.length === 1 ? 'is' : 'are'} your own.` }));
      status.appendChild(UI.el('div', { text: `Your folder: ${data.dir}`
        + (data.dir_exists ? '' : '  (not made yet — fetching one makes it)') }));

      mine.innerHTML = '';
      const chips = UI.el('div', { class: 'hint' });
      for (const row of data.installed) {
        chips.appendChild(UI.el('span', {
          class: row.where === 'yours' ? 'badge ok' : 'badge',
          text: row.name,
          title: row.where === 'yours' ? `yours: ${row.path}` : 'came with GROMACS',
        }));
        chips.appendChild(document.createTextNode(' '));
      }
      mine.appendChild(chips);

      shop.innerHTML = '';
      shop.appendChild(UI.el('h4', { text: 'Ones you can fetch' }));
      const grid = UI.el('table', { class: 'info-table' });
      grid.appendChild(UI.el('tr', {}, [
        UI.el('th', { text: 'force field' }), UI.el('th', { text: 'what it is' }),
        UI.el('th', { text: '' }),
      ]));
      for (const entry of data.available) {
        const button = UI.el('button', {
          class: 'small', text: entry.have ? 'Fetch again' : 'Fetch',
          title: entry.have
            ? 'this one is already here; fetching replaces it'
            : `download it from ${entry.source} and put it in ${data.dir}`,
          onclick: () => this.fetchForcefield({ id: entry.id }, entry.id, paint),
        });
        grid.appendChild(UI.el('tr', {}, [
          UI.el('td', {}, [
            UI.el('div', { text: entry.id }),
            entry.have ? UI.el('span', { class: 'badge ok', text: 'here' }) : null,
          ].filter(Boolean)),
          UI.el('td', {}, [
            UI.el('div', { class: 'hint', text: entry.note || entry.description }),
            UI.el('div', { class: 'hint', text: `from ${entry.source}` }),
          ]),
          UI.el('td', {}, [button]),
        ]));
      }
      shop.appendChild(grid);

      // The list above goes stale the moment a maintainer publishes a new
      // build, and it only covers what somebody thought to put in it. This is
      // the way round both.
      const url = UI.el('input', { type: 'text', placeholder:
        'https://.../something.ff.tgz' });
      const name = UI.el('input', { type: 'text', placeholder: 'name for the folder' });
      url.style.minWidth = '22em';
      const go = UI.el('button', { class: 'small', text: 'Fetch', onclick: () => {
        const typed = name.value.trim() || (url.value.split('/').pop() || '')
          .replace(/\.tar\.gz$|\.tgz$|\.tar$|\.zip$/, '').replace(/\.ff$/, '');
        if (!typed) { UI.toast('give the folder a name', 'warn'); return; }
        this.fetchForcefield({ url: url.value.trim(), name: typed }, typed, paint);
      } });
      shop.appendChild(UI.el('h4', { text: 'Or from an address you have' }));
      shop.appendChild(UI.el('div', { class: 'hint', text:
        'A .tgz or .tar.gz with a folder ending in .ff inside it. The name is '
        + 'what the topology block will list and what pdb2gmx is given; leave it '
        + 'blank and the file name is used. Anything already installed under '
        + 'that name is replaced, and only once the new one has arrived intact.' }));
      shop.appendChild(UI.el('div', { class: 'row' }, [url, name, go]));
    };

    paint();
    return wrap;
  },

  /* Do the fetching, with the log where every other install puts it. */
  async fetchForcefield(what, name, onDone) {
    const body = UI.el('div');
    body.appendChild(UI.el('p', { class: 'hint', text:
      `Fetching ${name}. It is a few hundred kilobytes; unpacked it is a few `
      + 'megabytes. Nothing already installed is touched until the new one has '
      + 'arrived and been checked.' }));
    const output = UI.el('pre', { class: 'log' });
    body.appendChild(output);
    UI.modal(`Force field: ${name}`, body, [{ label: 'Close' }],
      { reopen: () => this.environments() });

    let job;
    try {
      job = await API.installForcefield(what);
    } catch (err) {
      output.textContent = err.message;
      return;
    }
    output.textContent = `fetching from ${job.url}\ninto ${job.dir}\n\n`;
    this.watchJob(job.job, output, name);
    API.stream(`api/jobs/${job.job}/events`, (event) => {
      if (event.line !== undefined) {
        output.textContent += `${event.line}\n`;
        output.scrollTop = output.scrollHeight;
      }
      if (event.status && event.status !== 'running') {
        const ok = event.status === 'done';
        UI.toast(ok ? `${name} is installed — the Force field list has it now`
          : `${name} could not be fetched — the log says why`,
        ok ? 'ok' : 'error', 9000);
        // The catalogue the editor holds carries the list of force fields, so
        // it has to be re-read or the block would go on offering the old set.
        if (ok) App.refreshNodeDefs();
        if (onDone) onDone();
      }
    });
  },

  /* What the cache is holding, and a button to forget it.

     The word "clear" invites the wrong conclusion. What is stored is a few
     hundred kB of JSON saying "a node with this signature already ran, and its
     files are there"; the gigabytes are the run directories it points at, and
     clearing the index does not remove a single one of them. Somebody who
     presses this to free disk has done nothing but throw away the reason their
     next run would have been quick -- so the block says both numbers, and the
     button says what it does rather than "clear".

     Stale entries are worth showing separately: they are entries whose files
     have been deleted since, they cost nothing, and they disappear on their
     own the next time they are looked up. On this machine, 86 of 150. */
  cacheBlock() {
    const wrap = UI.el('div');
    const line = UI.el('div', { class: 'hint', text: 'counting…' });
    const button = UI.el('button', { class: 'small', text: 'Forget it' });
    const head = UI.el('div', { class: 'row' }, [line, button]);
    wrap.appendChild(head);
    wrap.appendChild(UI.el('div', { class: 'hint', text:
      'A node whose parameters and inputs have not changed is reused from the run '
      + 'that produced it, instead of running again — which is what makes changing '
      + 'one analysis parameter cost the analysis rather than the simulation. '
      + 'Forgetting it re-runs everything next time; it does not delete any results, '
      + 'and it frees no disk to speak of. Delete the run folders for that — the '
      + 'index is swept at every start, so entries pointing at folders you removed '
      + 'are already gone.' }));

    const load = async () => {
      let stats;
      try { stats = await API.cacheStats(); }
      catch (err) { line.textContent = err.message; return; }
      button.disabled = !stats.entries;
      line.textContent = stats.entries
        ? `${stats.live} node result${stats.live === 1 ? '' : 's'} ready to reuse, `
          + `in ${stats.runs} run folder${stats.runs === 1 ? '' : 's'} holding `
          + `${UI.bytes(stats.bytes)}${stats.partial ? '+' : ''}`
          + (stats.stale ? `. ${stats.stale} more point at files that are gone; `
            + 'those cost nothing and clear themselves.' : '.')
          + ` The index itself is ${UI.bytes(stats.index_bytes)}.`
        : 'nothing cached yet';
      button.title = stats.entries
        ? `Forget ${stats.entries} entries. The ${UI.bytes(stats.bytes)} of run `
          + 'files stays exactly where it is.'
        : '';
    };

    button.addEventListener('click', () => {
      API.cacheStats().then((stats) => {
        const ok = confirm(
          `Forget ${stats.live} reusable node result`
          + `${stats.live === 1 ? '' : 's'}?\n\n`
          + 'Every node runs again next time, however long that takes.\n'
          + `No files are deleted: the ${UI.bytes(stats.bytes)} in your run folders `
          + 'stays where it is, and this frees only the '
          + `${UI.bytes(stats.index_bytes)} index.`);
        if (!ok) return;
        API.clearCache()
          .then((done) => { UI.toast(`forgot ${done.cleared} cache entries`, 'ok'); load(); })
          .catch((err) => UI.toast(err.message, 'error'));
      }).catch((err) => UI.toast(err.message, 'error'));
    });

    load();
    return wrap;
  },

  /* What is on disk, and a way to get rid of one.

     Environments accumulate: a version tried once, an environment made by
     hand, one this created for a tool that has since moved in with another.
     Each is a gigabyte or two, and until now the only way to remove one was
     conda env remove in a terminal. Deleting is two steps -- the first says
     what would go and which tools resolve through it, because a couple of
     gigabytes should not leave on one click. */
  envList(report) {
    const wrap = UI.el('div');
    const envs = (report.conda_envs || []).filter((env) => env.name
      && !['base', 'root'].includes(env.name.toLowerCase()));
    if (!envs.length) {
      wrap.appendChild(UI.el('div', { class: 'hint', text:
        report.conda_root ? 'none besides base' : 'no conda installation found' }));
      return wrap;
    }
    // Which tools each one holds, so a row says what it is for.
    const holders = new Map();
    for (const [toolId, installs] of Object.entries(report.installs || {})) {
      const name = ((report.catalog || []).find((c) => c.id === toolId) || {}).name || toolId;
      for (const install of installs) {
        if (install.gone) continue;
        holders.set(install.env, (holders.get(install.env) || []).concat(name));
      }
    }
    const table = UI.el('table');
    for (const env of envs) {
      const tools = holders.get(env.name) || [];
      const remove = UI.el('button', {
        class: 'small danger', text: 'Delete',
        title: `remove ${env.path}`,
        onclick: () => this.removeEnv(env.name),
      });
      table.appendChild(UI.el('tr', {}, [
        UI.el('td', {}, [
          UI.el('div', { text: env.name }),
          UI.el('div', { class: 'hint', text: env.path }),
        ]),
        UI.el('td', {}, [UI.el('div', {
          class: 'hint',
          text: tools.length ? tools.join(', ') : 'no tool from the catalogue',
        })]),
        UI.el('td', {}, [remove]),
      ]));
    }
    wrap.appendChild(table);
    return wrap;
  },

  async removeEnv(env) {
    let plan;
    try {
      plan = await API.removeEnv(env, false);
    } catch (err) {
      UI.toast(err.message, 'error', 9000);
      return;
    }
    const output = UI.el('pre', { class: 'hidden' });
    const body = UI.el('div', {}, [
      UI.el('p', { text: `Delete the conda environment ${plan.env}?` }),
      UI.el('p', { class: 'hint', text: plan.path }),
      plan.holds.length
        ? UI.el('p', { class: 'warned', text:
          `${plan.holds.join(', ')} ${plan.holds.length === 1 ? 'lives' : 'live'} in it `
          + 'and will stop resolving until pointed somewhere else.' })
        : UI.el('p', { class: 'hint', text:
          'No tool from the catalogue resolves through it.' }),
      UI.el('p', { class: 'hint', text: 'This cannot be undone. Installing it again '
        + 'is a button, but whatever else is in there is gone.' }),
      output,
    ]);
    UI.modal(`Delete ${plan.env}`, body, [
      { label: 'Keep it' },
      {
        label: 'Delete it', primary: true,
        action: () => {
          output.classList.remove('hidden');
          output.textContent = '';
          API.removeEnv(env, true).then((job) => {
            this.watchJob(job.job, output, `removing ${env}`);
            API.stream(`api/jobs/${job.job}/events`, (event) => {
              if (event.line !== undefined) {
                this.appendOutput(output, event);
                if (!event.replace) Terminal.say(event.line, `removing ${env}`);
              }
              if (event.status === 'done') {
                UI.toast(`${env} removed`, 'ok', 7000);
                App.refreshEnvInfo();
                this.environments();
              } else if (event.status === 'error') {
                UI.toast(`could not remove ${env} — the log is above`, 'error', 12000);
              }
            });
          }).catch((err) => UI.toast(err.message, 'error', 9000));
          return false;
        },
      },
    ], { reopen: () => this.removeEnv(env) });
  },

  /* Building GROMACS the way you actually want it.

     The conda package is one build with one set of choices: no GPU, no MPI,
     and SIMD for whatever machine made it. Everything people actually complain
     about -- "why is it not using my card", "why can I not run this across
     nodes" -- is a build-time flag, so this offers the flags and shows exactly
     what it is going to run before it starts. It takes the better part of an
     hour and nothing about that can be helped. */
  async gromacs(row = null) {
    const field = (label, input, hint) => UI.el('div', { class: 'field' }, [
      UI.el('label', { text: label }), input,
      hint ? UI.el('div', { class: 'hint', text: hint }) : null,
    ].filter(Boolean));

    const version = UI.el('select');
    const prefix = UI.el('input', { type: 'text', placeholder: '~/soft/gromacs/gromacs-…' });
    const gpu = UI.el('select');
    for (const backend of ['none', 'CUDA', 'OpenCL', 'SYCL', 'HIP']) {
      gpu.appendChild(UI.el('option', { value: backend, text: backend }));
    }
    // Filled in from the first plan, which knows what is installed here.
    let gpuLabelled = false;
    const simd = UI.el('select');
    for (const level of ['AUTO', 'SSE2', 'SSE4.1', 'AVX_128_FMA', 'AVX_256', 'AVX2_128',
      'AVX2_256', 'AVX_512', 'ARM_NEON_ASIMD', 'ARM_SVE', 'None']) {
      simd.appendChild(UI.el('option', { value: level, text: level }));
    }
    const mpi = UI.el('input', { type: 'checkbox' });
    const dbl = UI.el('input', { type: 'checkbox' });
    const fftw = UI.el('input', { type: 'checkbox' });
    fftw.checked = true;
    const tests = UI.el('input', { type: 'checkbox' });
    const force = UI.el('input', { type: 'checkbox' });
    const keep = UI.el('input', { type: 'checkbox' });
    const jobs = UI.el('input', { type: 'number', min: '1', value: String(
      navigator.hardwareConcurrency || 8) });
    const suffix = UI.el('input', { type: 'text', placeholder: 'e.g. _2026' });
    const extra = UI.el('input', { type: 'text', placeholder: '-DGMX_OPENMP=ON …' });

    const notes = UI.el('div', { class: 'hint' });
    const hardware = UI.el('div', { class: 'hint' });
    const blocked = UI.el('div', { class: 'hidden' });
    const preview = UI.el('pre', { text: 'choose a version…' });
    const output = UI.el('pre', { class: 'hidden' });

    const options = () => ({
      version: version.value,
      prefix: prefix.value.trim(),
      gpu: gpu.value,
      simd: simd.value,
      mpi: mpi.checked,
      double: dbl.checked,
      own_fftw: fftw.checked,
      tests: tests.checked,
      force: force.checked,
      keep_build: keep.checked,
      jobs: Number(jobs.value) || 4,
      suffix: suffix.value.trim(),
      extra_cmake: extra.value.trim(),
    });

    let plan = null;
    let pending = 0;
    const refresh = async () => {
      if (!version.value) return;
      // Two changes in quick succession are two requests in flight, and the
      // slower one must not paint over the newer answer.
      const mine = ++pending;
      try {
        const fresh = await API.gromacsPlan(options());
        if (mine !== pending) return;
        plan = fresh;
        preview.textContent = plan.script;
        notes.innerHTML = '';
        notes.appendChild(UI.el('div', { text:
          `installs to ${plan.prefix}, binary ${plan.binary}` }));
        for (const note of plan.notes || []) {
          notes.appendChild(UI.el('div', { class: 'warned', text: `• ${note}` }));
        }
        // An hour of compiling should not start because a button looked
        // available. When it is already there the button says what it would do.
        // By class, not by its own label: the label is what this changes, so
        // matching on it worked once and then never found the button again.
        // Which backends this machine could actually build, said in the list
        // rather than found out by cmake ninety seconds in.
        if (!gpuLabelled && plan.gpus) {
          gpuLabelled = true;
          for (const option of gpu.options) {
            const state = plan.gpus.backends[option.value] || {};
            option.textContent = option.value
              + (option.value === 'none' ? ''
                : (state.available ? ' — installed' : ' — toolkit not installed'));
          }
          const devices = (plan.gpus.devices || [])
            .map((d) => d.vendor + (d.integrated ? ' (integrated)' : '')).join(', ');
          hardware.textContent = devices
            ? `This machine has: ${devices}. Suggested: ${plan.gpus.suggested}.`
            : 'No graphics device found; CPU only.';
          // Only when the dialog opens, never over a choice already made.
          if (!version.dataset.gpuPicked) {
            gpu.value = plan.gpus.suggested || 'none';
            version.dataset.gpuPicked = '1';
            refresh();
            return;
          }
        }

        // A build that cannot start should not be offered. The script checks
        // the same things -- it has to, it can be copied elsewhere -- but
        // finding out two seconds in that cmake is missing, with no idea what
        // to do about it, is the version of this that happened.
        const short = ((plan.toolchain || {}).missing || []);
        const gpuBad = plan.gpu_ok === false;
        blocked.innerHTML = '';
        blocked.classList.toggle('hidden', !short.length && !gpuBad);
        if (gpuBad) {
          const state = plan.gpu_state || {};
          blocked.appendChild(UI.el('p', { class: 'warned', text:
            `${gpu.value} is selected and its toolkit is not installed here. cmake `
            + 'would stop with "Could not find a package configuration file".' }));
          if (state.note) {
            blocked.appendChild(UI.el('p', { class: 'hint', text: state.note }));
          }
          if (state.command) {
            blocked.appendChild(UI.el('p', { class: 'hint', text:
              'Installing it needs root, so run this in a terminal:' }));
            blocked.appendChild(UI.el('div', { class: 'row' }, [
              UI.el('code', { text: state.command }),
              UI.el('button', { class: 'small', text: 'Copy',
                onclick: () => UI.copy(state.command) }),
            ]));
          }
          blocked.appendChild(UI.el('p', { class: 'hint', text:
            `Or set GPU to ${plan.gpus ? plan.gpus.suggested : 'none'} and build now — `
            + 'GROMACS on CPU is not a consolation prize.' }));
        }
        if (short.length) {
          this.requirementPanel(blocked, plan.toolchain, 'build GROMACS');
        }

        // Only if this dialog is still the one on screen. The plan is a
        // network call, and pressing "Set up this machine…" while it is in
        // flight puts a different dialog in front -- whose button would
        // otherwise be relabelled "Missing build tools" and greyed out.
        const build = mine() && document.querySelector('#modal-footer button.primary');
        if (build) {
          build.textContent = gpuBad ? `${gpu.value} toolkit missing`
            : short.length ? 'Missing build tools'
            : (plan.already ? 'Already installed'
              : (plan.existing ? 'Rebuild, replacing it' : 'Build it'));
          build.disabled = Boolean(plan.already) || short.length > 0 || gpuBad;
        }
        if (!prefix.value.trim()) prefix.placeholder = plan.prefix;
      } catch (err) {
        preview.textContent = err.message;
        plan = null;
      }
    };
    for (const el of [version, prefix, gpu, simd, mpi, dbl, fftw, tests, force, keep,
                      jobs, suffix, extra]) {
      el.addEventListener('change', refresh);
    }

    const body = UI.el('div', {}, [
      UI.el('p', { class: 'hint', text:
        'The only way to get GROMACS here, and the reason: a build carries its own '
        + 'choices — GPU support, MPI, a SIMD level for the machine that will run it. '
        + 'It compiles for the better part of an hour and wants a few GB of disk '
        + 'while it does.' }),
      blocked,
      field('Version', version, 'read from the GROMACS ftp index'),
      field('Install into', prefix,
        'somewhere you can write. A system prefix needs sudo, which this will not ask '
        + 'for on your behalf — copy the script and run it yourself instead.'),
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'GPU' }), gpu, hardware,
        UI.el('div', { class: 'hint', text:
          'CUDA for NVIDIA, HIP for AMD, SYCL for Intel. The toolkit has to be '
          + 'installed already — this only sets the flag, and the list says which '
          + 'ones are here.' }),
      ]),
      field('SIMD', simd, 'AUTO detects the machine doing the building, which is wrong '
        + 'exactly when that is not the machine that will run it.'),
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'Build options' }),
        UI.el('div', { class: 'row wrap' }, [
          UI.el('label', { class: 'check' }, [mpi, ' MPI (installs gmx_mpi)']),
          UI.el('label', { class: 'check' }, [dbl, ' double precision']),
          UI.el('label', { class: 'check' }, [fftw, ' build its own FFTW']),
          UI.el('label', { class: 'check' }, [tests, ' run the test suite']),
          UI.el('label', { class: 'check' }, [force, ' build it again anyway']),
          UI.el('label', { class: 'check' }, [keep, ' keep the build tree (~900 MB)']),
        ]),
      ]),
      field('Parallel jobs', jobs, 'make -j'),
      field('Binary suffix', suffix, 'so several builds can live side by side', true),
      field('Extra cmake flags', extra, 'appended verbatim'),
      notes,
      UI.el('h3', { text: 'What will run' }),
      preview,
      output,
    ]);

    const buttons = [
      { label: 'Close' },
      { label: 'Copy script', action: () => { UI.copy(preview.textContent); return false; } },
      {
        label: 'Build it',
        primary: true,
        action: () => {
          if (!plan) { UI.toast('nothing to build yet', 'warn'); return false; }
          if (plan.already) {
            UI.toast(`GROMACS ${plan.existing} is already at ${plan.prefix}. Tick `
              + '"build it again anyway", or change the prefix to keep both.', 'warn', 10000);
            return false;
          }
          output.classList.remove('hidden');
          output.textContent = '';
          API.gromacsBuild(options()).then((job) => {
            UI.toast(`building GROMACS ${version.value} — this takes a while`, 'info', 9000);
            this.watchJob(job.job, output, `GROMACS ${version.value}`);
            API.stream(`api/jobs/${job.job}/events`, (event) => {
              if (event.line !== undefined) this.appendOutput(output, event);
              if (event.status === 'done') {
                UI.toast(`GROMACS ${version.value} installed and registered `
                  + `(${job.binary} via ${job.gmxrc})`, 'ok', 15000);
              } else if (event.status === 'error') {
                UI.toast('the build failed — the log is above, and the build tree is '
                  + `left in ${job.workdir}`, 'error', 15000);
              }
            });
          }).catch((err) => UI.toast(err.message, 'error', 12000));
          return false;
        },
      },
    ];
    // Opened from inside another dialog -- "Set up this machine" has a
    // "Build from source…" button next to GROMACS -- this goes on the layer
    // above. It used to replace that dialog, and coming back re-drew it from
    // scratch: every tool ticked by hand was back to the suggested set, and
    // the "add conda to my shell startup" tick was off again.
    if (UI.modalOpen()) UI.subModal('Build GROMACS from source', body, buttons, { wide: true });
    else UI.modal('Build GROMACS from source', body, buttons, { reopen: () => this.gromacs(row) });
    generation = UI._generation;

    // Versions arrive after the dialog does.
    try {
      const found = await API.versions('gmx');
      const list = (found.versions || []).slice().reverse();
      for (const value of list) {
        version.appendChild(UI.el('option', { value, text: value }));
      }
      version.value = (row && row.latest) || found.latest || list[0] || '';
      refresh();
    } catch (err) {
      preview.textContent = `could not read the release list: ${err.message}`;
    }
  },

  /* A Stop button, for as long as a job is running.

     An hour-long build with no way to stop it is a trap -- the only exit was
     finding the process group by hand. It replaces the footer's primary button
     while the job runs and goes away when it ends. */
  watchJob(jobId, output, what) {
    const footer = document.getElementById('modal-footer');
    const stop = UI.el('button', { class: 'danger', text: `Stop ${what}` });
    stop.addEventListener('click', async () => {
      stop.disabled = true;
      try {
        const result = await API.cancelJob(jobId);
        UI.toast(result.cancelled ? `stopping ${what}…` : `${what} had already finished`,
          result.cancelled ? 'warn' : 'info', 7000);
      } catch (err) {
        UI.toast(err.message, 'error', 9000);
        stop.disabled = false;
      }
    });
    footer.appendChild(stop);
    const done = () => stop.remove();
    API.stream(`api/jobs/${jobId}/events`, (event) => {
      if (event.status && event.status !== 'running') done();
    }, done);
    return stop;
  },

  /* What is installed against what exists, for everything at once. */
  async checkUpdates() {
    const body = UI.el('div');
    body.appendChild(UI.el('p', { class: 'hint', text:
      'Asking each index what it has. Conda is slow about this — twenty seconds a '
      + 'package — which is why it is a button rather than something the dialog does '
      + 'by itself.' }));
    const table = UI.el('div', { class: 'hint', text: 'looking…' });
    body.appendChild(table);
    // With a reopen, going into an install from this list can come back to it.
    UI.modal('Updates', body, [{ label: 'Close' }], { reopen: () => this.checkUpdates() });

    let rows;
    try {
      rows = (await API.updates()).tools;
    } catch (err) {
      table.textContent = err.message;
      return;
    }
    table.innerHTML = '';
    const grid = UI.el('table', { class: 'info-table' });
    grid.appendChild(UI.el('tr', {}, [
      UI.el('th', { text: 'tool' }), UI.el('th', { text: 'installed' }),
      UI.el('th', { text: 'newest' }), UI.el('th', { text: '' }), UI.el('th', { text: '' }),
    ]));
    let behind = 0;
    for (const row of rows) {
      if (row.newer) behind += 1;
      const state = !row.present ? UI.el('span', { class: 'badge missing', text: 'not installed' })
        : row.newer ? UI.el('span', { class: 'badge warn', text: 'update available' })
          : row.latest ? UI.el('span', { class: 'badge ok', text: 'current' })
            : UI.el('span', { class: 'hint', text: row.note || 'unknown' });
      const act = row.latest && (row.newer || !row.present)
        ? UI.el('button', {
          class: 'small', text: row.present ? 'Update' : 'Install',
          onclick: () => {
            const tool = (this._report.tools || []).find((t) => t.id === row.id);
            if (row.id === 'gmx') this.gromacs(row);
            else if (tool) this.install(tool);
          },
        })
        : null;
      grid.appendChild(UI.el('tr', {}, [
        UI.el('td', { text: row.name }),
        UI.el('td', { text: row.installed || '—' }),
        UI.el('td', { class: row.newer ? 'kind-protein' : '', text: row.latest || '—' }),
        UI.el('td', {}, [state]),
        UI.el('td', {}, act ? [act] : []),
      ]));
    }
    table.appendChild(grid);
    table.appendChild(UI.el('div', { class: 'hint', text: behind
      ? `${behind} tool(s) have a newer release. Updating replaces what is in that `
        + 'environment — a workflow that ran against the old one may not run the same '
        + 'way against the new one.'
      : 'everything that could be checked is current.' }));
  },

  /* `options.version` is where the version box starts. A workflow that was
     built somewhere else says which version it used, and offering to install
     that one is the difference between running the same thing and running
     something like it. */
  async install(tool, options = {}) {
    const base = tool.suggested_env || `comfygmx-${tool.id}`;
    const asked = String(options.version || '').trim();
    const envInput = UI.el('input', {
      type: 'text', value: tool.env || base,
    });
    // Asking for a specific version means asking for it *as well*, not instead:
    // the environment name follows the version so a second one lands beside the
    // first rather than over the top of a working install.
    let envTouched = false;
    envInput.addEventListener('input', () => { envTouched = true; });
    const versionInput = UI.el('select');
    if (asked) {
      // Ahead of "newest", and chosen: this dialog was opened to install that
      // one. The list from the index is added underneath when it arrives.
      versionInput.appendChild(UI.el('option', {
        value: asked, text: `${asked} — the version the workflow used`,
      }));
    }
    // "newest available" is untrue wherever the catalogue holds a version back
    // on purpose -- dssp stays at 3.1.4 because every conda 4.x build is broken
    // one way or another -- so the blank option names what it will install.
    const held = /[=<>]/.test(tool.primary || '') ? tool.primary : '';
    versionInput.appendChild(UI.el('option', {
      value: '', text: held ? `default (${held})` : 'newest available',
    }));
    if (asked) {
      versionInput.value = asked;
      envInput.value = tool.env || `${base}-${asked}`;
    }
    const versionHint = UI.el('div', { class: 'hint', text: tool.versions_from
      ? 'listing versions…' : 'this one does not come from an index that can be listed' });
    const preview = UI.el('pre', { text: 'loading the install script…' });
    const output = UI.el('pre', { class: 'hidden' });
    const blocked = UI.el('div', { class: 'hidden' });

    const body = UI.el('div', {}, [
      blocked,
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'Conda environment' }), envInput,
        UI.el('div', {
          class: 'hint',
          text: 'An existing environment is updated in place rather than replaced. '
              + 'Picking a version names the environment after it, so it installs '
              + 'beside what you already have instead of over it.',
        }),
      ]),
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'Version' }), versionInput, versionHint,
      ]),
      UI.el('h3', { text: 'What will run' }),
      preview,
      output,
    ]);

    let pending = 0;
    const refresh = async () => {
      const mine = ++pending;
      try {
        const data = await API.installScript(tool.id, envInput.value.trim(),
                                             versionInput.value);
        if (mine !== pending) return;
        preview.textContent = data.script;
      } catch (err) {
        if (mine === pending) preview.textContent = err.message;
      }
    };
    envInput.addEventListener('change', refresh);
    versionInput.addEventListener('change', () => {
      if (!envTouched) {
        envInput.value = versionInput.value ? `${base}-${versionInput.value}` : base;
      }
      refresh();
    });
    refresh();

    /* Whether this can be installed at all, before the button says it can:
       conda for anything that goes into an environment, and git for a recipe
       that installs straight from a repository. Without this the script gets
       as far as pip and stops there. */
    API.requirements(tool.id).then((kit) => {
      if (!kit.missing.length) return;
      blocked.classList.remove('hidden');
      this.requirementPanel(blocked, kit, `install ${tool.name}`);
      // As above: this answer can arrive after somebody has moved on, and it
      // must not grey out whatever button is in front of them now.
      const button = mine() && document.querySelector('#modal-footer button.primary');
      if (button) {
        button.textContent = `${kit.missing.length === 1 ? 'Requirement' : 'Requirements'} missing`;
        button.disabled = true;
      }
    }).catch(() => {});

    // Listing versions is a network call of its own, so the dialog opens
    // straight away and fills the list in when it arrives.
    if (tool.versions_from) {
      API.versions(tool.id).then((found) => {
        const list = (found.versions || []).slice().reverse();
        for (const version of list) {
          // Not twice: the one the workflow asked for is already at the top.
          if (version === asked) continue;
          versionInput.appendChild(UI.el('option', { value: version, text: version }));
        }
        if (asked && !list.includes(asked)) {
          versionHint.classList.add('warn');
          versionHint.textContent =
            `${asked} is not on ${found.source} any more — install the newest `
            + 'instead, or ask whoever sent you the workflow where they got it.';
          return;
        }
        versionHint.textContent = list.length
          ? `${list.length} on ${found.source}, newest ${found.latest}`
          : (found.note || 'nothing found on the index');
      }).catch((err) => { versionHint.textContent = err.message; });
    }

    UI.modal(`Install ${tool.name}`, body, [
      { label: 'Copy script', action: () => { UI.copy(preview.textContent); return false; } },
      {
        label: 'Run install',
        primary: true,
        action: () => {
          output.classList.remove('hidden');
          output.textContent = '';
          API.install(tool.id, envInput.value.trim(), versionInput.value).then((job) => {
            this.watchJob(job.job, output, tool.name);
            UI.toast(`installing ${tool.name} into ${job.env}…`, 'info', 6000);
            API.stream(`api/jobs/${job.job}/events`, (event) => {
              if (event.type === 'log') {
                this.appendOutput(output, event);
              } else if (event.type === 'job') {
                if (event.status !== 'done') {
                  UI.toast(`${tool.name}: install failed (exit ${event.rc}) — see the log`,
                    'error', 12000);
                  return;
                }
                // Ask the tool itself rather than trusting the installer: a
                // package can install cleanly and still fail on first import.
                API.probe(tool.id).then((result) => {
                  output.textContent +=
                    `\n>> probe: ${result.found ? result.version : (result.error || 'not found')}\n`;
                  if (!result.found && result.troubleshooting) {
                    output.textContent += `\n${result.troubleshooting}\n`;
                  }
                  output.scrollTop = output.scrollHeight;
                  UI.toast(
                    result.found
                      ? `${tool.name} installed and working — ${result.version}`
                      : `${tool.name} installed but not usable: ${result.error || 'see the log'}`,
                    result.found ? 'ok' : 'error', 12000);
                }).catch((err) => UI.toast(err.message, 'error'));
              }
            });
          }).catch((err) => UI.toast(err.message, 'error'));
          return false;
        },
      },
      { label: 'Close' },
    ], { reopen: () => this.install(tool) });
    generation = UI._generation;
  },

  /* ------------------------------------------------------------ settings */
  /* `edits` carries what was typed back in when this dialog has to be rebuilt
     -- which happens when the output-folder picker opens over it. Without it,
     browsing for one folder would quietly discard every other change on the
     form. */
  async settings(edits = {}) {
    const current = Object.assign(await API.settings(), edits);
    const report = await API.environment(false);
    let forcefields = null;
    try { forcefields = await API.gmxForcefields(); } catch (err) { forcefields = null; }

    const field = (label, input, hint) => UI.el('div', { class: 'field' }, [
      UI.el('label', { text: label }), input,
      hint ? UI.el('div', { class: 'hint', text: hint }) : null,
    ]);

    const gmxrc = UI.el('input', { type: 'text', value: current.gmxrc || '',
      placeholder: '/path/to/gromacs/bin/GMXRC — blank uses whatever gmx is on PATH' });
    const binary = UI.el('input', { type: 'text', value: current.gmx_binary || 'gmx' });
    const installs = gmxInstallList(report, current, (candidate, chosen) => {
      gmxrc.value = candidate.path;
      binary.value = chosen;
    });
    const roots = UI.el('textarea', { rows: '3',
      placeholder: 'one directory per line — searched in addition to the built-in list' });
    roots.value = (current.gmx_search_roots || []).join('\n');

    const condaRoot = UI.el('input', { type: 'text', value: current.conda_root || '',
      placeholder: report.conda_root || 'auto-detected' });
    const dataDir = UI.el('input', { type: 'text', value: current.data_dir || '' });
    const outputDir = UI.el('input', { type: 'text', value: current.output_dir || '',
      placeholder: 'blank puts runs under <data directory>/runs' });
    const workflowDirs = UI.el('textarea', { rows: '3',
      placeholder: 'one directory per line — listed in the Open dialog' });
    workflowDirs.value = (current.workflow_dirs || []).join('\n');
    const ntomp = UI.el('input', { type: 'number', min: '0',
      value: String((current.mdrun || {}).ntomp || 0) });
    const ntmpi = UI.el('input', { type: 'number', min: '0',
      value: String((current.mdrun || {}).ntmpi || 0) });
    const gpu = UI.el('input', { type: 'text', value: (current.mdrun || {}).gpu_id || '' });
    const nice = UI.el('input', { type: 'checkbox' });
    nice.checked = current.nice !== false;
    const pointer = UI.el('select', {}, [
      UI.el('option', { value: 'mouse', text: 'a mouse: the wheel zooms' }),
      UI.el('option', { value: 'trackpad',
                        text: 'a trackpad: two fingers slide the canvas' }),
    ]);
    pointer.value = Editor.pointer();
    // Takes effect at once and saves itself. Nothing else in this dialog does
    // that, but this one has to: it is a thing you judge by trying, and having
    // to press Save and come back to find out is how a setting goes untried.
    pointer.addEventListener('change', () => {
      Editor.setPointer(pointer.value);
      UI.toast(pointer.value === 'trackpad'
        ? 'two fingers now slide the canvas; pinch, or Ctrl and two fingers, zooms'
        : 'the wheel now zooms again', 'ok', 7000);
    });
    const parallel = UI.el('input', { type: 'number', min: '1', max: '16',
      value: String(current.max_parallel_nodes || 1) });
    const ffDir = UI.el('input', { type: 'text', value: current.gmx_forcefield_dir || '',
      placeholder: (forcefields && forcefields.dir) || '<data directory>/forcefields/gromacs' });

    /* A folder box with two buttons: copy the path, and open it on the
       desktop so a downloaded force field can be dragged straight in. */
    const folderRow = (label, input, actual, hint) => {
      const pathOf = () => input.value.trim() || actual;
      const copy = UI.el('button', { class: 'small', text: 'Copy path', onclick: () => {
        navigator.clipboard.writeText(pathOf()).then(() => UI.toast('path copied', 'ok'))
          .catch(() => UI.toast(pathOf(), 'info'));
      } });
      const open = UI.el('button', { class: 'small', text: 'Open folder', onclick: () => {
        API.openFolder(pathOf()).then((r) => {
          if (r.opened) UI.toast('opened in your file manager', 'ok');
          else UI.toast(`${r.why || 'could not open it'}: ${r.path}`, 'info');
        }).catch((err) => UI.toast(err.message, 'error'));
      } });
      return field(label, UI.el('div', { class: 'row' }, [input, copy, open]),
        `${hint} Path: ${actual || '(not set)'}`);
    };

    const body = UI.el('div', {}, [
      UI.el('h3', { text: 'GROMACS' }),
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'Installations found' }),
        installs,
      ]),
      field('GMXRC to source', gmxrc,
        'Sourced with set +u because GMXRC reads $shell and $GMXLDLIB before assigning them.'),
      field('Binary name', binary,
        'gmx, gmx_mpi, gmx_mpi_d — or a full command such as "mpirun -np 4 gmx_mpi". '
        + 'An MPI build installs no plain "gmx", so this has to match the selected install.'),
      field('Search roots', roots,
        'Directories to walk when looking for installations. Add one if your build '
        + 'lives somewhere unusual; nested prefixes such as .../inst/cuda-mpi are found automatically.'),

      UI.el('h3', { text: 'Force fields' }),
      folderRow('Your GROMACS force fields (.ff folders)', ffDir,
        (forcefields && forcefields.dir) || '',
        'Drop a folder ending in .ff in here -- charmm36-jul2022.ff, say -- and it '
        + 'appears in the Force field list on the Topology (pdb2gmx) block, next to '
        + 'the ones GROMACS came with. Blank means the folder under the data directory.'
        + (forcefields && forcefields.user.length
          ? ` Found here now: ${forcefields.user.join(', ')}.` : ' Nothing of your own in it yet.')
        + (forcefields && forcefields.builtin.length
          ? ` GROMACS itself has ${forcefields.builtin.length}, in ${forcefields.gmx_top}.` : '')),

      UI.el('h3', { text: 'Default mdrun resources' }),
      UI.el('div', { class: 'row' }, [
        field('-ntomp', ntomp), field('-ntmpi', ntmpi), field('-gpu_id', gpu),
      ]),
      UI.el('div', { class: 'hint',
        text: 'Used when an mdrun node leaves the corresponding field at 0. 0 means "let GROMACS decide".' }),

      UI.el('h3', { text: 'General' }),
      field('Nodes at once', parallel,
        'How many nodes may run together when the graph allows it — four analyses '
        + 'hanging off one trajectory share nothing but their input, and running them '
        + 'one after another is three quarters of the wall clock wasted. Simulation '
        + 'nodes are exempt: mdrun takes every core it can see, so it waits for the '
        + 'rest and runs on its own. Set this to 1 for strictly one node at a time.'),
      field('Conda root', condaRoot, 'Where etc/profile.d/conda.sh lives.'),
      field('Data directory', dataDir, 'Uploads, the node output cache and saved workflows.'),
      field('Workflow folders', workflowDirs,
        'Extra places the Open dialog lists .json workflows from. The data directory '
        + 'and the ones that ship with Comfy-gmx are always listed; add your project '
        + 'folder here to keep workflows next to the data they produced.'),
      field('Default output folder',
        UI.el('div', { class: 'row' }, [
          outputDir,
          UI.el('button', {
            class: 'small', text: 'Browse…',
            // The picker opens on the layer above this page, so this page is
            // still here underneath with everything typed into it: the chosen
            // folder goes straight into the box. It used to replace this page
            // and re-draw it from a snapshot of the boxes afterwards, which
            // worked when a folder was chosen and lost the lot when the picker
            // was cancelled.
            onclick: () => {
              Pick.folder({
                title: 'Default output folder',
                start: outputDir.value.trim() || App.outputRoot || App.homeDir,
                extra: [{ label: 'home', path: App.homeDir }].filter((s) => s.path),
                onPick: (path) => { outputDir.value = path; },
              });
            },
          }),
        ]),
        'Where run directories are created, for sessions that have not chosen their own. '
        + 'Trajectories live here, so a scratch disk beats a home directory. Each session '
        + 'can override it from the button in the session bar.'),
      UI.el('div', { class: 'field' }, [
        UI.el('label', {}, [nice, ' run commands under nice/ionice']),
        UI.el('div', { class: 'hint',
          text: 'Keeps a long mdrun from making the rest of the workstation unusable.' }),
      ]),

      // Saved in this browser rather than in the settings file, because it
      // describes the thing under your hand and not the machine doing the
      // work. Open the same server from a desktop and from a laptop and each
      // remembers its own answer. It also takes effect the moment it changes,
      // with no Save, which is the only way to try it and see.
      UI.el('h3', { text: 'This browser' }),
      field('What you are pointing with', pointer,
        'A mouse wheel turns to zoom; on a trackpad, two fingers sliding is how '
        + 'you move around, and the browser reports that as the wheel turning. '
        + 'Set this to Trackpad and two fingers slide the canvas instead of '
        + 'zooming it. Pinching still zooms either way, and so does Ctrl with '
        + 'the wheel. Whichever you choose, holding the spacebar and dragging '
        + 'moves the canvas, which works on everything.'),
    ]);

    // What the form says right now -- read by Save, and by the folder picker,
    // which has to put every other field back when it rebuilds this dialog.
    const typed = () => ({
      gmxrc: gmxrc.value.trim(),
      gmx_binary: binary.value.trim() || 'gmx',
      gmx_search_roots: roots.value.split('\n').map((r) => r.trim()).filter(Boolean),
      conda_root: condaRoot.value.trim(),
      data_dir: dataDir.value.trim() || current.data_dir,
      output_dir: outputDir.value.trim(),
      workflow_dirs: workflowDirs.value.split('\n').map((d) => d.trim()).filter(Boolean),
      gmx_forcefield_dir: ffDir.value.trim(),
      nice: nice.checked,
      max_parallel_nodes: Math.max(1, Math.min(16, parseInt(parallel.value, 10) || 1)),
      mdrun: {
        ntomp: parseInt(ntomp.value, 10) || 0,
        ntmpi: parseInt(ntmpi.value, 10) || 0,
        gpu_id: gpu.value.trim(),
      },
    });

    UI.modal('Settings', body, [
      { label: 'Cancel' },
      {
        label: 'Save',
        primary: true,
        action: () => {
          API.saveSettings(typed()).then(() => UI.toast('settings saved', 'ok'))
            .catch((err) => UI.toast(err.message, 'error'));
        },
      },
    ]);
  },

  /* --------------------------------------------- a workflow's programs */
  /* A workflow that arrived from somewhere else, and the programs it needs
     that this machine has not got.

     Every node drives some program, and which ones a workflow needs is not
     something you can see by looking at it. Without this you find out when the
     run stops on the fourth node, an hour in.

     The version matters as much as the program. Two versions of a
     coarse-graining tool do not produce the same model, so "install the
     newest" is not the same answer as "install what this was built with" --
     and which of those you want depends on whether you are reproducing
     somebody's work or starting your own. Both are offered; the workflow's own
     version is the default when it says what that was. */
  workflowTools(missing) {
    const body = UI.el('div', {}, [
      UI.el('p', { class: 'hint', text:
        `This workflow needs ${missing.length === 1 ? 'a program' : 'programs'} `
        + 'this machine has not got. Nothing is broken -- the nodes that use '
        + `${missing.length === 1 ? 'it' : 'them'} will stop when they are `
        + 'reached, and the rest of the workflow runs as it is.' }),
    ]);

    for (const tool of missing) {
      const versions = UI.el('select');
      if (tool.wanted) {
        versions.appendChild(UI.el('option', {
          value: tool.wanted, text: `${tool.wanted} — what this workflow used`,
        }));
      }
      versions.appendChild(UI.el('option', { value: '', text: 'the newest available' }));
      if (tool.wanted) versions.value = tool.wanted;

      const rows = [
        UI.el('div', { class: 'wt-name' }, [
          UI.el('b', { text: tool.name }),
          tool.optional ? UI.el('span', { class: 'hint', text: ' — optional' }) : null,
        ].filter(Boolean)),
        UI.el('div', { class: 'hint', text: tool.description }),
        UI.el('div', { class: 'hint', text:
          `Needed by: ${tool.titles.join(', ')}` }),
      ];

      if (tool.installable) {
        rows.push(UI.el('div', { class: 'row' }, [
          UI.el('label', { text: 'Version' }),
          versions,
          UI.el('button', {
            class: 'small', text: 'Install…',
            onclick: () => this.install(tool, { version: versions.value }),
          }),
        ]));
        rows.push(UI.el('div', { class: 'hint', text: tool.wanted
          ? 'The workflow says which version it was built with. Pick that one to '
            + 'reproduce what it did; pick the newest to start from here. They are '
            + 'not the same program and they need not give the same answer.'
          : 'This workflow does not say which version it was built with — it was '
            + 'saved before that was recorded, or on a machine without this '
            + 'program either. Only the newest is on offer.' }));
      } else {
        rows.push(UI.el('div', { class: 'hint warn', text:
          `${tool.name} is not one this can install for you`
          + (tool.wanted ? ` — the workflow was built with ${tool.wanted}.` : '.') }));
        rows.push(UI.el('div', { class: 'row' }, [
          UI.el('button', {
            class: 'small', text: 'Open Environments',
            onclick: () => this.environments(),
          }),
        ]));
      }
      body.appendChild(UI.el('div', { class: 'card wt-tool' }, rows));
    }

    body.appendChild(UI.el('p', { class: 'hint', text:
      'Each one opens the ordinary install dialog, which shows the script '
      + 'before it runs it and the log while it does. Environments lists them '
      + 'all again later, so nothing here has to be decided now.' }));

    UI.modal(missing.length === 1
      ? 'This workflow needs a program you have not got'
      : `This workflow needs ${missing.length} programs you have not got`,
      body, [{ label: 'Not now' }]);
  },

  /* -------------------------------------------------------- file browser */
  /* Choosing a file for a node's file box. The listing is the same one the
     Files tab and the folder picker draw -- there is no second idea of what a
     directory looks like in this program. */
  /* Where the picker was last left. Reopening it lands you back where you
     were rather than at your home directory again, which for a file three
     folders deep is the difference between one click and four. */
  _lastBrowsed: '',

  /* ------------------------------------------------ what a chunk takes in */
  /* One window listing everything a chunk needs from outside, so a chunk can
     be pointed at a different structure without opening the four blocks that
     happen to mention it.

     Nothing here is a new way of working: every row does exactly what you
     would have done by hand in the block itself, and the blocks still work
     the way they always did. This is a shortcut for the common job, not a
     replacement for anything.

     Two kinds of row, because a chunk takes things in two ways. A file box
     names something on disk and is changed by picking another file. A socket
     is fed by a wire from a block outside the chunk, or by nothing at all,
     and is changed by choosing a different block to feed it. */
  chunkInputs(group) {
    const show = () => {
      const { files, sockets } = Editor.chunkInputs(group);
      const body = UI.el('div', { class: 'chunk-inputs' });

      const missing = [].concat(files.filter((r) => r.kind === 'missing'),
                                sockets.filter((r) => r.kind === 'missing'));
      const fed = sockets.filter((r) => r.kind === 'fed');
      const named = files.filter((r) => r.kind === 'named');
      const spare = [].concat(sockets.filter((r) => r.kind === 'spare'),
                              files.filter((r) => r.kind === 'spare'));

      if (!missing.length && !fed.length && !named.length && !spare.length) {
        body.appendChild(UI.el('p', { class: 'hint', text:
          `Nothing comes into ${group.title} from outside. Every block in it is `
          + 'fed by another block in it, and none of them reads a file by name. '
          + 'If that is a surprise, the box may be drawn around fewer blocks than '
          + 'you think: only a block sitting wholly inside the box counts as '
          + 'being in it.' }));
        UI.modal(`Inputs — ${group.title}`, body, [{ label: 'Close' }],
                 { wide: true, reopen: show });
        return;
      }

      body.appendChild(UI.el('p', { class: 'hint', text:
        `Everything ${group.title} takes in from outside, in one place. Changing `
        + 'a row here does exactly what changing it in the block would do, and '
        + 'the block name on the left takes you to it on the canvas.' }));

      // A row's left-hand side: which block, and which box or socket on it.
      const naming = (row, what) => UI.el('div', { class: 'ci-where' }, [
        UI.el('button', {
          class: 'small link', text: `${row.node.title}${row.which || ''}`,
          title: 'Show me this block on the canvas',
          onclick: () => { UI.closeModal(); Editor.centreOn(row.node); Editor.select([row.node.id]); },
        }),
        UI.el('span', { class: 'ci-what', text: what }),
      ]);

      const fileRow = (row) => {
        const box = UI.el('input', { type: 'text', class: 'file-box',
                                     value: row.value,
                                     placeholder: row.param.placeholder || '' });
        const write = (path) => Editor.setParam(row.node, row.param.name, path,
                                                `${row.param.label} on ${row.node.title}`);
        box.addEventListener('change', () => {
          box.value = App.normalisePath(box.value);
          write(box.value);
        });
        const browse = UI.el('button', {
          class: 'small', text: 'Choose…',
          onclick: () => this.browseFile((path) => { box.value = path; write(path); },
                                         App.normalisePath(box.value || '')),
        });
        return UI.el('div', { class: 'ci-row' }, [
          naming(row, row.param.label),
          UI.el('div', { class: 'row' }, [box, browse]),
        ]);
      };

      const socketRow = (row) => {
        const pick = UI.el('select', {});
        const offer = (value, text, from) => {
          const option = UI.el('option', { value, text });
          if (from) {
            option.dataset.fromNode = from.node;
            option.dataset.fromPort = from.port;
          }
          pick.appendChild(option);
          return value;
        };
        offer('', 'nothing yet');
        let chosen = '';
        // The ones that carry what was asked for, then the ones this socket
        // would take but nobody meant -- a log file offered as an index. Kept
        // apart under headings so the second lot cannot be picked by accident.
        let heading = null;
        for (const source of Editor.chunkSourcesFor(group, row.port)) {
          const want = source.exact
            ? 'The kind of file this socket asks for'
            : 'Would be accepted, but is not that kind of file';
          if (heading !== want) {
            heading = want;
            pick.appendChild(UI.el('optgroup', { label: want }));
          }
          const holder = pick.lastElementChild;
          const value = `${pick.querySelectorAll('option').length}`;
          const option = UI.el('option', {
            value, text: `${source.node.title} — ${source.port.label}`,
          });
          option.dataset.fromNode = source.node.id;
          option.dataset.fromPort = source.port.name;
          holder.appendChild(option);
          if (row.link && row.link.from_node === source.node.id
            && row.link.from_port === source.port.name) chosen = value;
        }
        // A wire already drawn to something this list does not offer -- its
        // socket hidden by a setting since, say -- is kept and shown, not
        // silently swapped for "nothing yet" the moment the window opens.
        if (row.link && !chosen) {
          const source = Editor.nodes.get(row.link.from_node);
          chosen = offer(`${pick.children.length}`,
                         `${source ? source.title : row.link.from_node} — ${row.link.from_port}`,
                         { node: row.link.from_node, port: row.link.from_port });
        }
        pick.value = chosen;
        pick.addEventListener('change', () => {
          const picked = pick.selectedOptions[0];
          Editor.disconnect(row.node.id, row.port.name);
          if (picked && picked.dataset.fromNode) {
            Editor.connect(picked.dataset.fromNode, picked.dataset.fromPort,
                           row.node.id, row.port.name);
          }
          App.check(true);
        });
        if (pick.querySelectorAll('option').length <= 1 && !row.link) {
          return UI.el('div', { class: 'ci-row' }, [
            naming(row, row.port.label),
            UI.el('div', { class: 'hint', text:
              'Nothing outside this chunk produces this kind of file yet. Add a '
              + 'block that does and it will appear here.' }),
          ]);
        }
        return UI.el('div', { class: 'ci-row' }, [
          naming(row, row.port.label),
          UI.el('div', { class: 'row' }, [pick]),
        ]);
      };

      const section = (heading, hint, rows, draw) => {
        if (!rows.length) return;
        body.appendChild(UI.el('h3', { text: heading }));
        if (hint) body.appendChild(UI.el('div', { class: 'hint', text: hint }));
        for (const row of rows) body.appendChild(draw(row));
      };

      const eitherRow = (row) => (row.param ? fileRow(row) : socketRow(row));
      section('Still waiting for something',
              'These have to be filled in before the chunk will run.',
              missing, eitherRow);
      section('Coming from a block outside this chunk', '', fed, socketRow);
      section('Files read from disk', '', named, fileRow);

      // The rest are the ones nearly every chunk leaves alone: an optional
      // index file, a second way of giving a plot its data. Listing them with
      // the two that matter buries the two that matter.
      if (spare.length) {
        const more = UI.el('div', { class: 'hidden' });
        for (const row of spare) more.appendChild(eitherRow(row));
        const tick = UI.el('input', { type: 'checkbox' });
        tick.addEventListener('change', () =>
          more.classList.toggle('hidden', !tick.checked));
        body.appendChild(UI.el('label', { class: 'check ci-more' }, [tick,
          `Show the ${spare.length} optional one${spare.length === 1 ? '' : 's'} `
          + 'as well, which most graphs leave empty']));
        body.appendChild(more);
      }

      UI.modal(`Inputs — ${group.title}`, body, [{ label: 'Close' }],
               { wide: true, reopen: show });
    };
    show();
  },

  browseFile(onPick, startPath) {
    const pathInput = UI.el('input', { type: 'text', value: startPath || '', spellcheck: 'false' });
    const list = UI.el('div', { class: 'file-browser' });
    const upload = UI.el('input', { type: 'file' });
    upload.style.display = 'none';
    const search = UI.el('input', {
      type: 'text', class: 'fb-search',
      placeholder: 'name to look for — Enter looks in the folders below too',
    });
    let here = startPath || Panels._lastBrowsed || '';
    // Every folder walked out of, so Back means back rather than up. The two
    // are not the same: walking into a folder and out again leaves you where
    // you started, and Up alone cannot retrace that.
    const trail = [];
    let listing = null;     // the folder, as the server gave it
    let found = null;       // a search result, or null while showing a folder

    const parentOf = (path) => {
      const trimmed = String(path || '').replace(/\/+$/, '');
      const cut = trimmed.lastIndexOf('/');
      return cut > 0 ? trimmed.slice(0, cut) : '/';
    };

    const pick = (entry) => {
      Panels._lastBrowsed = here;
      onPick(entry.path);
      UI.closeModal();
    };

    const paint = () => {
      const needle = search.value.trim().toLowerCase();
      list.innerHTML = '';
      if (found) {
        const note = UI.el('div', { class: 'fb-note' }, [
          found.entries.length
            ? `${found.entries.length} match${found.entries.length === 1 ? '' : 'es'} in `
              + `${found.searched} folder${found.searched === 1 ? '' : 's'}`
              + (found.complete ? '' : ' — stopped early, so there may be more')
            : `nothing called "${needle}" under here`,
          ' ',
          UI.el('button', {
            class: 'small', text: 'back to the folder',
            onclick: () => { found = null; paint(); },
          }),
        ]);
        // parent set to path: the found rows are from all over, so there is
        // nothing sensible for ".." to mean in that list.
        renderListing(list, { path: found.path, parent: found.path,
                              entries: found.entries },
                      { note,
                        onEnter: (next) => { found = null; load(next); },
                        onFile: pick });
        return;
      }
      if (!listing) return;
      const shown = needle
        ? Object.assign({}, listing, {
          entries: listing.entries.filter((e) => e.name.toLowerCase().includes(needle)),
        })
        : listing;
      renderListing(list, shown, { onEnter: load, onFile: pick, filtered: !!needle });
      if (needle && !shown.entries.length) {
        list.appendChild(UI.el('div', { class: 'fb-note' }, [
          `nothing here is called "${needle}". `,
          UI.el('button', { class: 'small', text: 'Look in the folders below',
                            onclick: deepSearch }),
        ]));
      }
    };

    const load = async (path, remember = true) => {
      let data;
      try {
        data = await API.files(path || '');
      } catch (err) {
        // Handed a file's own path -- which is what the box next to the button
        // usually holds -- open the folder it is in rather than an error.
        const up = parentOf(path);
        if (path && up && up !== path) { load(up, remember); return; }
        list.innerHTML = '';
        list.appendChild(UI.el('div', { class: 'fb-note', text: err.message }));
        return;
      }
      if (remember && here && here !== data.path) trail.push(here);
      here = data.path;
      Panels._lastBrowsed = here;
      pathInput.value = data.path;
      listing = data;
      found = null;
      back.disabled = !trail.length;
      paint();
    };

    const deepSearch = async () => {
      const needle = search.value.trim();
      if (!needle) return;
      list.innerHTML = '';
      list.appendChild(UI.el('div', { class: 'fb-note searching',
                                      text: `looking for "${needle}" under ${here}…` }));
      try {
        found = await API.findFiles(here, needle);
      } catch (err) {
        list.innerHTML = '';
        list.appendChild(UI.el('div', { class: 'fb-note', text: err.message }));
        return;
      }
      paint();
    };

    const back = UI.el('button', {
      class: 'small', text: '← Back', title: 'The folder you were in before',
      onclick: () => {
        const previous = trail.pop();
        if (previous) load(previous, false);
        back.disabled = !trail.length;
      },
    });
    back.disabled = true;

    pathInput.addEventListener('change', () => load(pathInput.value.trim()));
    search.addEventListener('input', () => { found = null; paint(); });
    search.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); deepSearch(); }
      if (event.key === 'Escape') {
        event.preventDefault();
        search.value = '';
        found = null;
        paint();
      }
    });
    upload.addEventListener('change', async () => {
      if (!upload.files.length) return;
      try {
        const result = await API.upload(upload.files[0]);
        UI.toast(`uploaded ${result.name}`, 'ok');
        onPick(result.path);
        UI.closeModal();
      } catch (err) { UI.toast(err.message, 'error'); }
    });

    // The handful of folders worth one click. Read defensively: this dialog is
    // also opened from places that do not have a run.
    let runDir = '';
    try {
      if (typeof FileBrowser !== 'undefined' && FileBrowser.runDir) {
        runDir = FileBrowser.runDir() || '';
      }
    } catch (err) { runDir = ''; }
    const app = (typeof App !== 'undefined') ? App : {};
    const jumps = [
      { label: 'this run', path: runDir },
      { label: 'output folder', path: app.outputRoot || '' },
      { label: 'uploads', path: app.uploadsDir || '' },
      { label: 'home', path: app.homeDir || '' },
    ].filter((shortcut) => shortcut.path);

    const body = UI.el('div', {}, [
      UI.el('div', { class: 'row' }, [
        pathInput,
        UI.el('button', { class: 'small', text: 'Go',
                          onclick: () => load(pathInput.value.trim()) }),
        UI.el('button', { class: 'small', text: '↑ Up', title: 'The folder above this one',
                          onclick: () => load(parentOf(here)) }),
        back,
        UI.el('button', { class: 'small', text: 'Upload…', onclick: () => upload.click() }),
        UI.el('button', {
          class: 'small', text: 'Copy path', title: "Copy this folder's path",
          onclick: () => UI.copy(here),
        }),
      ]),
      jumps.length ? UI.el('div', { class: 'row wrap fb-jump' }, jumps.map((shortcut) =>
        UI.el('button', {
          class: 'small', text: shortcut.label, title: shortcut.path,
          onclick: () => load(shortcut.path),
        }))) : null,
      UI.el('div', { class: 'row' }, [
        search,
        UI.el('button', { class: 'small', text: 'Search below',
                          title: 'Look in this folder and everything under it',
                          onclick: deepSearch }),
        UI.el('button', {
          class: 'small', text: 'Clear',
          onclick: () => { search.value = ''; found = null; paint(); },
        }),
      ]),
      UI.el('div', { class: 'hint', text:
        'Typing hides everything here that does not match. Enter, or "Search '
        + 'below", looks through the folders underneath as well and shows where '
        + 'each answer lives.' }),
      upload,
      list,
    ].filter(Boolean));
    // Opened from inside another dialog -- a file box in a form, most often --
    // it goes on the layer above and leaves that dialog alone underneath.
    // Before there was a second layer this browser replaced whatever was on
    // screen, so choosing a file for a lipid threw away the form that asked
    // for it, along with everything typed into it.
    const buttons = [
      { label: 'Use this path', primary: true, action: () => onPick(pathInput.value.trim()) },
      { label: 'Cancel' },
    ];
    if (UI.modalOpen()) UI.subModal('Choose a file', body, buttons);
    else UI.modal('Choose a file', body, buttons);
    load(here);
  },

  /* ----------------------------------------------------------- workflows */
  /* Read a workflow .json straight off disk. Loading by *path* rather than by
     name matters once more than one directory is listed: two roots can hold
     the same name, and clicking a row has to open the one you clicked. */
  async loadWorkflowFile(path, onLoad) {
    if (!/\.json$/i.test(path)) {
      UI.toast('a workflow is a .json file', 'warn');
      return false;
    }
    try {
      const file = await API.fileText(path);
      const graph = JSON.parse(file.text);
      const inner = graph.graph && graph.graph.nodes ? graph.graph : graph;
      if (!inner.nodes) throw new Error('that .json is not a workflow');
      const name = path.split('/').pop().replace(/\.json$/i, '');
      onLoad(name, inner);
      return true;
    } catch (err) {
      UI.toast(err.message, 'error');
      return false;
    }
  },

  async openWorkflow(onLoad) {
    let data;
    try { data = await API.workflows(); }
    catch (err) { UI.toast(err.message, 'error'); return; }

    const list = UI.el('div', { class: 'file-browser' });
    const items = data.workflows || [];
    const roots = data.roots || [{ label: 'saved here', path: data.directory, writable: true }];

    // Grouped by where it came from: your own saves, the examples that ship
    // with Comfy-gmx, and the packaged tutorials are three different things.
    // Empty roots are still listed, so it is obvious where Save will write.
    for (const root of roots) {
      const mine = items.filter((item) => item.source === root.label);
      list.appendChild(UI.el('div', { class: 'cat-title wf-group', title: root.path }, [
        UI.el('span', { text: root.label }),
        UI.el('span', { class: 'fb-size', text: root.path }),
      ]));
      if (!mine.length) {
        list.appendChild(UI.el('div', { class: 'fb-row empty', text: 'nothing here yet' }));
      }
      for (const item of mine) {
        const open = async () => {
          UI.closeModal();
          await Panels.loadWorkflowFile(item.path, onLoad);
        };
        const row = UI.el('div', { class: 'fb-row' }, [
          UI.el('span', { text: `📄 ${item.name}` }),
          UI.el('span', {
            class: 'fb-size',
            text: new Date(item.modified * 1000).toLocaleDateString(),
          }),
          item.writable ? UI.el('button', {
            class: 'small', text: 'Delete',
            onclick: async (event) => {
              event.stopPropagation();
              if (!confirm(`Delete workflow "${item.name}"?`)) return;
              try { await API.deleteWorkflow(item.name); }
              catch (err) { UI.toast(err.message, 'error'); return; }
              UI.closeModal();
              Panels.openWorkflow(onLoad);
            },
          }) : UI.el('span', { class: 'fb-size', text: 'read-only' }),
        ]);
        row.addEventListener('click', open);
        list.appendChild(row);
      }
    }

    const body = UI.el('div', {}, [
      UI.el('div', { class: 'hint',
        text: 'Save writes to the first directory below. The others are read-only, '
            + 'and open a copy: saving keeps your version separate. '
            + 'Add more in Settings.' }),
      list,
    ]);
    UI.modal('Open workflow', body, [
      { label: 'Cancel' },
      {
        label: 'Browse…',
        action: () => {
          // A workflow is a plain .json and may live anywhere -- next to the
          // data it produced, most usefully.
          setTimeout(() => Panels.browseFile(async (path) => {
            if (await Panels.loadWorkflowFile(path, onLoad)) {
              UI.toast(`opened ${path}`, 'ok');
            }
          }, roots[0] ? roots[0].path : ''), 0);
        },
      },
    ]);
  },

  saveWorkflow(currentName, graph) {
    const nameInput = UI.el('input', { type: 'text', value: currentName || 'my-workflow' });
    const where = UI.el('div', { class: 'hint', text: '' });
    API.workflows()
      .then((data) => { where.textContent = `saved in ${data.directory}`; })
      .catch(() => { where.textContent = ''; });
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'field' }, [UI.el('label', { text: 'Name' }), nameInput]),
      where,
    ]);
    UI.modal('Save workflow', body, [
      { label: 'Cancel' },
      {
        label: 'Save',
        primary: true,
        action: () => {
          API.saveWorkflow(nameInput.value.trim(), graph)
            .then((result) => {
              App.workflowName = result.saved;
              UI.toast(`saved as ${result.saved}`, 'ok');
            })
            .catch((err) => UI.toast(err.message, 'error'));
        },
      },
    ]);
  },

  /* --------------------------------------------------------- save a chunk */

  /* Turn a selection into something reusable. The section is free text with
     the sections you already have offered as suggestions: one heading per kind
     of work is what stops a long list of chunks becoming unreadable. */
  saveChunk(graph, defaults = {}) {
    const sections = [...new Set((App.chunks || [])
      .filter((c) => c.custom && c.category)
      .map((c) => c.category))].sort();

    const nameInput = UI.el('input', { type: 'text', value: defaults.name || '' });
    nameInput.placeholder = 'Water box + ions';
    const listId = 'chunk-sections';
    const sectionInput = UI.el('input', { type: 'text', list: listId, value: defaults.category || '' });
    sectionInput.placeholder = 'optional — a heading under "Custom chunks"';
    const datalist = UI.el('datalist', { id: listId });
    for (const section of sections) datalist.appendChild(UI.el('option', { value: section }));
    const descInput = UI.el('textarea', { rows: '3' });
    descInput.value = defaults.description || '';
    descInput.placeholder = 'what it does, and what you still have to set afterwards';

    const counts = UI.el('div', {
      class: 'hint',
      text: `${graph.nodes.length} nodes · ${graph.links.length} links`
        + (graph.groups.length ? ` · ${graph.groups.length} group(s)` : ''),
    });
    const body = UI.el('div', {}, [
      UI.el('div', { class: 'field' }, [UI.el('label', { text: 'Name' }), nameInput]),
      UI.el('div', { class: 'field' }, [UI.el('label', { text: 'Section' }), sectionInput, datalist]),
      UI.el('div', { class: 'field' }, [UI.el('label', { text: 'Description' }), descInput]),
      counts,
      UI.el('div', { class: 'hint', text: 'Parameters are saved as they are now, so set '
        + 'what you want the chunk to start from before saving it.' }),
    ]);

    UI.modal('Save as chunk', body, [
      { label: 'Cancel' },
      {
        label: 'Save',
        primary: true,
        action: () => {
          const name = nameInput.value.trim();
          if (!name) { UI.toast('a chunk needs a name', 'warn'); return false; }
          API.saveChunk({
            name,
            category: sectionInput.value.trim(),
            description: descInput.value.trim(),
            graph,
          })
            .then((result) => {
              UI.toast(`saved "${result.chunk.name}" under Custom chunks`, 'ok', 5000);
              App.refreshChunks();
            })
            .catch((err) => UI.toast(err.message, 'error', 9000));
          return true;
        },
      },
    ]);
    setTimeout(() => nameInput.focus(), 30);
  },

  /* ------------------------------------------------------- save a file */

  /* Two ways to keep a structure you are looking at, because they are not the
     same thing: a download hands it to the browser's download folder, and a
     copy puts it where the data lives on the machine that produced it. */
  saveFile(path, defaults = {}) {
    const name = path.split('/').pop();
    const dirInput = UI.el('input', {
      type: 'text',
      value: defaults.destination || Panels._lastSaveDir || '',
    });
    dirInput.placeholder = '/scratch/me/results';
    const nameInput = UI.el('input', { type: 'text', value: defaults.name || name });
    const onExists = UI.el('select');
    for (const [value, label] of [['overwrite', 'overwrite it'],
                                  ['timestamp', 'keep both, add a timestamp'],
                                  ['stop', 'stop and tell me']]) {
      onExists.appendChild(UI.el('option', { value, text: label }));
    }
    onExists.value = defaults.onExists || 'overwrite';

    const browse = UI.el('button', {
      class: 'small', text: '…', title: 'browse',
      onclick: () => {
        // There is one modal, so the file browser replaces this dialog rather
        // than stacking on it. Carry the other fields over and come back.
        const carried = { name: nameInput.value, onExists: onExists.value };
        Panels.browseFile((picked) => {
          // Navigate into the folder and press "Use this path", or click a file
          // inside it -- both should mean the same folder.
          const dir = /\.[A-Za-z0-9]{1,8}$/.test(picked)
            ? picked.replace(/\/[^/]*$/, '') : picked;
          Panels.saveFile(path, { destination: dir, ...carried });
        }, dirInput.value || '');
      },
    });

    const body = UI.el('div', {}, [
      UI.el('div', { class: 'hint', text: path }),
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'Save into' }),
        UI.el('div', { class: 'row' }, [dirInput, browse]),
      ]),
      UI.el('div', { class: 'field' }, [UI.el('label', { text: 'Save as' }), nameInput]),
      UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'If it is already there' }), onExists,
      ]),
      UI.el('div', { class: 'hint', text: 'The copy is made on the machine running '
        + 'Comfy-gmx, so nothing large travels through the browser.' }),
    ]);

    UI.modal(`Save ${name}`, body, [
      { label: 'Cancel' },
      {
        label: 'Download instead',
        action: () => {
          const link = UI.el('a', { href: API.downloadUrl(path), download: name });
          document.body.appendChild(link);
          link.click();
          link.remove();
        },
      },
      {
        label: 'Save',
        primary: true,
        action: () => {
          const destination = dirInput.value.trim();
          if (!destination) { UI.toast('no folder to save into', 'warn'); return false; }
          API.copyFile({
            source: path,
            destination,
            name: nameInput.value.trim() || name,
            on_exists: onExists.value,
          })
            .then((result) => {
              Panels._lastSaveDir = destination;
              UI.toast(`saved ${result.path} (${UI.bytes(result.size)})`, 'ok', 7000);
            })
            .catch((err) => UI.toast(err.message, 'error', 12000));
          return true;
        },
      },
    ]);
  },

  /* --------------------------------------------- choosing a box by eye */

  /* "How big a box does this need?" answered by looking at it.

     Typing 1.2 into a box marked "solute-box distance" tells a newcomer
     nothing: not what the number is measured between, not what happens if it
     is too small, and not that the box shape underneath it changes the cost of
     the run by a third. So the molecule is drawn, the box is drawn round it,
     and every number that follows from the two is shown as it changes.

     What the numbers mean, since this is the panel where it has to be said:
     GROMACS builds the box from ONE measurement -- the distance between the
     two atoms of your molecule that are furthest apart -- plus the gap you
     ask for at each end. The shape then only decides how much of the corners
     is thrown away. */
  boxAround(data, node) {
    const span = data.span || {};
    const diameter = Number(span.diameter) || 0;
    const shapes = data.shapes || [];
    const shapeOf = (name) => shapes.find((s) => s.type === name) || shapes[0] || {};
    const nSolute = data.n_solute || 0;
    const perAtom = 0.0080;          // matches SOLUTE_NM3_PER_ATOM in viz.py
    const perNm3 = 32.3;             // matches WATERS_PER_NM3

    // How far the molecule reaches along x, y and z as the file has it, and
    // how far it reaches along its own three directions once turned to lie
    // along the axes. The second is what makes a hand-set box worth having:
    // a long molecule lying across a corner measures its own diagonal three
    // times over, so all three sides come out far too big.
    const AXES = ['x', 'y', 'z'];
    const asItSits = AXES.map((axis) => {
      const pair = (data.extent || {})[axis] || [0, 0];
      return Math.max(0, pair[1] - pair[0]);
    });
    const alignedSides = ((data.aligned || {}).lengths) || null;

    const state = {
      type: node.params.box_type || 'dodecahedron',
      distance: Number(node.params.distance) || 1.2,
      // Only used by the "sides set by hand" shape.
      align: Boolean(alignedSides),
      sides: null,
    };

    // What the molecule measures along each box axis in the mode we are in.
    const reach = () => (state.align && alignedSides ? alignedSides : asItSits);
    const resetSides = () => {
      state.sides = reach().map((len) => Number((len + 2 * state.distance).toFixed(2)));
    };
    const byHand = () => state.type === 'triclinic';

    const share = { cubic: 1.0, triclinic: 1.0, dodecahedron: 0.7071, octahedron: 0.7698 };
    const edge = () => diameter + 2 * state.distance;
    const volume = () => (byHand()
      ? state.sides[0] * state.sides[1] * state.sides[2]
      : (edge() ** 3) * (share[state.type] || 1));
    const waters = () => Math.max(0, Math.round((volume() - nSolute * perAtom) * perNm3));
    // The nearest the molecule comes to the copy of itself next door, one
    // answer per side: the side minus how far the molecule reaches along it.
    const clearances = () => reach().map((len, i) => state.sides[i] - len);

    const body = UI.el('div', { class: 'box-picker box-around' });
    body.appendChild(Forms.ui.hint(
      'GROMACS builds the box from one measurement: how far apart the two atoms '
      + 'of your molecule that are furthest apart are. That distance, plus the '
      + 'gap you ask for at each end, is the edge of the box. The shape only '
      + 'decides how much of the corners is cut off.'));

    const measured = UI.el('div', { class: 'box-measured' }, [
      UI.el('div', { class: 'box-figure-number' }, [
        UI.el('b', { text: `${diameter.toFixed(2)} nm` }),
        UI.el('span', { text: ' across at its widest — '
          + `${data.name}, ${nSolute.toLocaleString()} atoms`
          + (data.n_solvent ? `, ignoring ${data.n_solvent.toLocaleString()} `
             + 'water and ion atoms' : '') }),
      ]),
    ]);
    body.appendChild(measured);

    const canvas = UI.el('canvas', { class: 'box-canvas', width: 640, height: 210 });
    body.appendChild(canvas);
    const caption = UI.el('div', { class: 'hint' });
    body.appendChild(caption);

    // ---- the two things you choose ------------------------------------
    const shapeRow = UI.el('div', { class: 'box-shapes' });
    const shapeButtons = new Map();
    const readout = UI.el('div', { class: 'box-readout' });
    const warnings = UI.el('div');

    // ---- one number per side, for when the molecule is not round ---------
    //
    // GROMACS builds its usual box from a single measurement: the distance
    // between the two atoms furthest apart. For anything roughly round that is
    // the right measurement. For something long and thin it is far too much in
    // two directions out of three -- a 48 nm molecule gets a 48 nm box in x, y
    // and z, and the extra is water nobody wanted.
    const sideBox = UI.el('div', { class: 'box-sides hidden' });
    const sideRows = [];
    const alignCheck = UI.el('input', { type: 'checkbox' });
    alignCheck.checked = state.align;

    sideBox.appendChild(Forms.ui.hint(
      'One number per side instead of one number for all three. Worth having '
      + 'when the molecule is much longer than it is wide: the sides it does '
      + 'not need stay small, and everything you leave out is water you do not '
      + 'have to simulate.'));

    if (alignedSides) {
      const row = UI.el('div', { class: 'field' }, [
        UI.el('label', { class: 'check' }, [alignCheck,
          ' turn the molecule to lie along the axes first (-princ)']),
        UI.el('div', { class: 'hint', text:
          'A long molecule lying across a corner of the file measures its own '
          + 'diagonal in all three directions at once, so every side comes out '
          + 'too big. Turning it first puts its longest direction along x, the '
          + 'middle one along y and the shortest along z. Here that is '
          + `${asItSits.map((v) => v.toFixed(1)).join(' × ')} nm as the file has `
          + `it, against ${alignedSides.map((v) => v.toFixed(1)).join(' × ')} nm `
          + 'turned.' }),
      ]);
      alignCheck.addEventListener('change', () => {
        state.align = alignCheck.checked;
        resetSides();
        syncSides();
        refresh();
      });
      sideBox.appendChild(row);
    }

    ['x', 'y', 'z'].forEach((axis, index) => {
      const slider = UI.el('input', { type: 'range', step: '0.05', class: 'box-slider' });
      const number = UI.el('input', { type: 'number', min: '0', step: '0.1',
                                      class: 'box-distance' });
      const note = UI.el('div', { class: 'hint' });
      const set = (value) => {
        if (!Number.isFinite(value) || value <= 0) return;
        state.sides[index] = Number(value.toFixed(2));
        syncSides();
        refresh();
      };
      slider.addEventListener('input', () => set(Number(slider.value)));
      number.addEventListener('input', () => set(Number(number.value)));
      sideRows.push({ slider, number, note });
      sideBox.appendChild(Forms.ui.field(`Side along ${axis} (nm)`,
        UI.el('div', { class: 'row box-distance-row' }, [slider, number])));
      sideBox.appendChild(note);
    });

    sideBox.appendChild(UI.el('button', {
      class: 'ghost', text: 'Snug again — the gap above, on every side',
      onclick: () => { resetSides(); syncSides(); refresh(); },
    }));

    function syncSides() {
      if (!state.sides) return;
      const base = reach();
      const names = (state.align && alignedSides)
        ? ['x, the longest direction', 'y, the middle one', 'z, the shortest']
        : ['x', 'y', 'z'];
      sideRows.forEach((row, index) => {
        // The bottom of the slider is a side that only just clears the cutoff,
        // so the warning below can actually be reached by dragging.
        row.slider.min = (base[index] + 1.0).toFixed(2);
        row.slider.max = (base[index] + 8.0).toFixed(2);
        row.slider.value = String(state.sides[index]);
        if (document.activeElement !== row.number) {
          row.number.value = state.sides[index].toFixed(2);
        }
        row.note.textContent = `${names[index]}: ${base[index].toFixed(2)} nm of `
          + `molecule and ${(state.sides[index] - base[index]).toFixed(2)} nm of `
          + 'clear space';
      });
    }

    const draw = () => {
      const ctx = canvas.getContext('2d');
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);
      const half = W / 2;
      const views = [
        { key: 'xy', points: (data.points || {}).xy || [], label: 'seen from above (x, y)' },
        { key: 'xz', points: (data.points || {}).xz || [], label: 'seen from the front (x, z)' },
      ];
      const L = edge();
      // In hand-set mode the two sides on view are different lengths, so the
      // picture has to be drawn to the longest side of the pair and the box
      // drawn as the rectangle it really is.
      const handSides = byHand() ? state.sides : null;
      views.forEach((view, index) => {
        const x0 = index * half;
        const pad = 34;
        const size = Math.min(half - pad * 2, H - pad * 2);
        const cx = x0 + half / 2;
        const cy = H / 2;
        // Everything is drawn to the same scale: the box edge fills `size`, so
        // the molecule inside is exactly as big as it really is relative to it.
        const pair = handSides
          ? [handSides[0], view.key === 'xy' ? handSides[1] : handSides[2]]
          : [L, L];
        const scale = size / Math.max(pair[0], pair[1]);
        const boxW = pair[0] * scale;
        const boxH = pair[1] * scale;
        const mid = data.centre || { x: 0, y: 0, z: 0 };
        const midA = view.key === 'xy' ? mid.x : mid.x;
        const midB = view.key === 'xy' ? mid.y : mid.z;

        ctx.save();
        // the box
        ctx.strokeStyle = '#4f9dd8';
        ctx.lineWidth = 1.5;
        if (handSides) {
          ctx.strokeRect(cx - boxW / 2, cy - boxH / 2, boxW, boxH);
        } else if (state.type === 'cubic') {
          ctx.strokeRect(cx - size / 2, cy - size / 2, size, size);
        } else {
          // A dodecahedron and an octahedron are a cube with the corners taken
          // off; drawn as such, because that is what they are and it is why
          // they hold less water.
          const c = state.type === 'dodecahedron' ? 0.29 : 0.23;
          const s = size / 2, k = size * c;
          ctx.beginPath();
          ctx.moveTo(cx - s + k, cy - s);
          ctx.lineTo(cx + s - k, cy - s);
          ctx.lineTo(cx + s, cy - s + k);
          ctx.lineTo(cx + s, cy + s - k);
          ctx.lineTo(cx + s - k, cy + s);
          ctx.lineTo(cx - s + k, cy + s);
          ctx.lineTo(cx - s, cy + s - k);
          ctx.lineTo(cx - s, cy - s + k);
          ctx.closePath();
          ctx.stroke();
          ctx.setLineDash([3, 4]);
          ctx.strokeStyle = '#2d6d9c';
          ctx.strokeRect(cx - s, cy - s, size, size);
          ctx.setLineDash([]);
        }
        // the molecule
        if (handSides && state.align && alignedSides) {
          // Turned to lie along the axes, which is not how the atoms are
          // stored, so what is drawn is the space it takes up rather than the
          // atoms themselves. Drawing the untouched scatter here would show a
          // molecule lying across the box it is about to be straightened in.
          const mw = alignedSides[0] * scale;
          const mh = (view.key === 'xy' ? alignedSides[1] : alignedSides[2]) * scale;
          ctx.fillStyle = 'rgba(111, 191, 139, 0.45)';
          ctx.fillRect(cx - mw / 2, cy - mh / 2, Math.max(mw, 1), Math.max(mh, 1));
        } else {
          ctx.fillStyle = 'rgba(111, 191, 139, 0.7)';
          for (const point of view.points) {
            const px = cx + (point[0] - midA) * scale;
            const py = cy - (point[1] - midB) * scale;
            ctx.fillRect(px - 0.8, py - 0.8, 1.6, 1.6);
          }
        }
        // the gap, drawn as the thing the number actually measures
        ctx.strokeStyle = '#d8a84f';
        ctx.setLineDash([2, 3]);
        if (handSides) {
          // One rectangle per side, because in this mode the number that
          // matters is how far the molecule reaches along each axis, not its
          // longest diagonal.
          const rw = reach()[0] * scale;
          const rh = (view.key === 'xy' ? reach()[1] : reach()[2]) * scale;
          ctx.strokeRect(cx - rw / 2, cy - rh / 2, Math.max(rw, 1), Math.max(rh, 1));
        } else {
          const r = (diameter / 2) * scale;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.setLineDash([]);
        ctx.fillStyle = '#8d97a5';
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(view.label, cx, H - 10);
        ctx.restore();
      });
      caption.textContent = byHand()
        ? ('Green is the space your molecule takes up' + (state.align && alignedSides
            ? ', after being turned so its longest direction lies along x' : '')
          + '. The dotted rectangle is how far it reaches along each side, and '
          + 'the gap between that and the wall is what you are setting — one '
          + 'number per side, which is the point of this shape.')
        : ('Green is your molecule. The dotted circle is the '
          + 'distance between its two furthest atoms — usually a diagonal, so it '
          + 'looks wider than the molecule does from any one side, and that is '
          + 'exactly why GROMACS uses it. The gap between the circle and the wall '
          + 'is the number you are setting. The faint square is the cube the '
          + 'cut-cornered shapes are cut from.');
    };

    const paintShapes = () => {
      for (const [name, button] of shapeButtons) {
        button.classList.toggle('chosen', name === state.type);
      }
    };

    const refresh = () => {
      if (byHand() && !state.sides) resetSides();
      sideBox.classList.toggle('hidden', !byHand());
      const L = edge();
      const V = volume();
      const N = waters();
      const cube = (L ** 3) - nSolute * perAtom;
      const cubeWaters = Math.max(1, Math.round(cube * perNm3));
      readout.innerHTML = '';
      const line = (label, value, note) => {
        const row = UI.el('div', { class: 'box-line' }, [
          UI.el('span', { class: 'box-line-label', text: label }),
          UI.el('b', { text: value }),
        ]);
        if (note) row.appendChild(UI.el('span', { class: 'box-line-note', text: note }));
        readout.appendChild(row);
      };
      if (byHand()) {
        const gaps = clearances();
        line('Box sides', state.sides.map((v) => v.toFixed(2)).join(' × ') + ' nm',
          'x, y, z -- the three numbers editconf will be given');
        line('Volume', `${V.toFixed(0)} nm³`);
        line('Water it will hold', `about ${N.toLocaleString()} molecules`);
        line('Distance to its own image',
          gaps.map((v) => v.toFixed(2)).join(' / ') + ' nm',
          'along x / y / z -- the closest your molecule comes to the copy next door');
      } else {
        line('Box edge', `${L.toFixed(3)} nm`,
          `${diameter.toFixed(2)} across + ${state.distance.toFixed(2)} at each end`);
        line('Volume', `${V.toFixed(0)} nm³`);
        line('Water it will hold', `about ${N.toLocaleString()} molecules`,
          state.type === 'cubic' ? ''
            : `${Math.round(100 - 100 * N / cubeWaters)}% fewer than a cube`);
        line('Distance to its own image', `${(2 * state.distance).toFixed(2)} nm`,
          'the closest your molecule comes to the copy of itself next door');
      }

      warnings.innerHTML = '';
      const say = (text, bad) => warnings.appendChild(
        UI.el('div', { class: `hint${bad ? ' warned' : ''}`, text }));
      if (byHand()) {
        const gaps = clearances();
        const tightest = Math.min(...gaps);
        const which = ['x', 'y', 'z'][gaps.indexOf(tightest)];
        if (tightest < 1.2) {
          say(`Only ${tightest.toFixed(2)} nm of clear space along ${which}. Ordinary `
            + 'force fields keep counting interactions out to about 1.2 nm, so at '
            + 'this size your molecule is still feeling the copy of itself next '
            + 'door and the answer is quietly wrong. Give that side at least '
            + `${(reach()[gaps.indexOf(tightest)] + 2.4).toFixed(2)} nm.`, true);
        } else if (tightest < 2.0) {
          say(`${tightest.toFixed(2)} nm of clear space along ${which} clears the `
            + 'usual 1.2 nm cutoff, but leaves the molecule little room to move '
            + 'before it does not. Fine for something held in place; tight for '
            + 'anything free.');
        }
        // The reason a hand-set box is not simply better: it is a box shaped to
        // one particular pose, and a molecule left to itself does not keep one.
        say('A box shaped to the molecule is only right while the molecule keeps '
          + 'that shape and stays pointing the same way. Anything long and free '
          + 'will slowly turn, and a shape that fitted at the start will not fit '
          + 'later. Hold it with position restraints, or keep the run short, or '
          + 'check afterwards with "gmx mindist -f traj.xtc -s topol.tpr -pi", '
          + 'which reports the closest the molecule ever came to its own image.');
        const round = Math.max(1, Math.round(
          (((diameter + 2 * state.distance) ** 3) * 0.7071 - nSolute * perAtom) * perNm3));
        if (round > N * 1.1) {
          say(`A rhombic dodecahedron with the same ${state.distance.toFixed(2)} nm gap `
            + `would hold about ${round.toLocaleString()} waters. This box holds `
            + `${N.toLocaleString()} -- ${(round / Math.max(N, 1)).toFixed(1)} times `
            + 'less to simulate, which is where the time goes.');
        }
      }
      if (!byHand() && state.distance < 0.9) {
        say(`A gap of ${state.distance.toFixed(2)} nm puts your molecule `
          + `${(2 * state.distance).toFixed(2)} nm from the copy of itself in the `
          + 'next box. Ordinary force fields stop counting interactions at about '
          + '1.2 nm, so at this size the two are still feeling each other and the '
          + 'answer is quietly wrong. 1.0 nm is the usual smallest.', true);
      } else if (!byHand() && state.distance > 1.5) {
        // What the extra gap costs, in the only currency that matters here.
        const lean = Math.max(1, Math.round(
          (((diameter + 2 * 1.2) ** 3) * (share[state.type] || 1)
            - nSolute * perAtom) * perNm3));
        say(`A gap of ${state.distance.toFixed(2)} nm is generous. At 1.2 nm this `
          + `box would hold about ${lean.toLocaleString()} waters instead of `
          + `${N.toLocaleString()}, and water is most of what a run spends its `
          + `time on -- so this setting is costing roughly `
          + `${Math.round(100 * N / lean - 100)}% more time than 1.2 nm would.`);
      }
      if (state.type === 'cubic') {
        const dodeca = Math.max(1, Math.round(
          ((L ** 3) * 0.7071 - nSolute * perAtom) * perNm3));
        say(`A rhombic dodecahedron would hold about ${dodeca.toLocaleString()} `
          + `waters instead of ${N.toLocaleString()} -- the same room around your `
          + 'molecule, ' + `${Math.round(100 - 100 * dodeca / N)}% less water to `
          + 'simulate. It is the usual choice for anything roughly round.');
      }
      // A deposited structure has no hydrogens; pdb2gmx puts them on, and they
      // stick out further than anything else. Measuring the bare file gives a
      // box a few percent small, so say so instead of being quietly wrong.
      if (!data.hydrogens) {
        say('This file has no hydrogens in it yet. Building the topology adds '
          + 'them, and they stick out past everything else, so the box GROMACS '
          + 'actually builds will be roughly 3% bigger than the numbers here. '
          + 'Run the topology step first and ask again if you want them exact.');
      }
      draw();
      paintShapes();
    };

    for (const name of ['cubic', 'dodecahedron', 'octahedron', 'triclinic']) {
      const info = shapeOf(name);
      const button = UI.el('button', {
        class: 'box-shape',
        onclick: () => { state.type = name; if (name === 'triclinic') resetSides();
                         syncSides(); refresh(); },
      }, [
        UI.el('div', { class: 'box-shape-name', text:
          name === 'triclinic' ? 'set each side yourself' : (info.label || name) }),
        UI.el('div', { class: 'box-shape-note', text:
          name === 'cubic' ? 'the obvious one, and the most water'
          : name === 'dodecahedron' ? '29% less water, same room around the molecule'
          : name === 'octahedron' ? '23% less water; suits a long molecule'
          : 'sides set by hand -- far less water for a long thin molecule' }),
      ]);
      shapeButtons.set(name, button);
      shapeRow.appendChild(button);
    }
    body.appendChild(Forms.ui.field('Box shape', shapeRow));

    const slider = UI.el('input', { type: 'range', min: '0.5', max: '2.5',
                                    step: '0.05', class: 'box-slider' });
    slider.value = String(state.distance);
    const number = UI.el('input', { type: 'number', min: '0', step: '0.1',
                                    class: 'box-distance' });
    number.value = state.distance.toFixed(2);
    slider.addEventListener('input', () => {
      state.distance = Number(slider.value);
      number.value = state.distance.toFixed(2);
      // In hand-set mode this slider is the "same gap on every side" shortcut,
      // so moving it re-fits the three sides rather than doing nothing.
      if (byHand()) { resetSides(); syncSides(); }
      refresh();
    });
    number.addEventListener('input', () => {
      const wanted = Number(number.value);
      if (!Number.isFinite(wanted) || wanted < 0) return;
      state.distance = wanted;
      slider.value = String(Math.min(2.5, Math.max(0.5, wanted)));
      refresh();
    });
    body.appendChild(Forms.ui.field('Gap between the molecule and the wall (nm)',
      UI.el('div', { class: 'row box-distance-row' }, [slider, number]),
      'The one number that decides whether the answer is right. Everything else '
      + 'here only decides how long it takes.'));

    body.appendChild(sideBox);
    body.appendChild(readout);
    body.appendChild(warnings);

    if (byHand()) { resetSides(); }
    syncSides();
    refresh();
    UI.modal('How big a box?', body, [
      { label: 'Leave it as it was' },
      {
        label: 'Use this box',
        primary: true,
        action: () => {
          Editor.setParam(node, 'box_type', state.type, `box shape on ${node.title}`);
          Editor.setParam(node, 'distance', Number(state.distance.toFixed(2)),
                          `box gap on ${node.title}`);
          if (byHand()) {
            const sides = state.sides.map((v) => v.toFixed(2)).join(' ');
            Editor.setParam(node, 'box', sides, `box sides on ${node.title}`);
            Editor.setParam(node, 'princ', state.align, `turn first on ${node.title}`);
            if (state.align && !String(node.params.groups || '').trim()) {
              // -princ asks which part of the file to turn, and waits for an
              // answer. Nobody sees that prompt here, so the run would sit
              // there for ever. "System" means the whole file, which is what
              // is wanted when there is only a molecule in it.
              Editor.setParam(node, 'groups', 'System', `group on ${node.title}`);
            }
            UI.toast(`${sides} nm -- about ${waters().toLocaleString()} waters`
              + (state.align ? ', turned to lie along the axes first' : ''), 'ok');
          } else {
            // Leaving an old explicit box behind would quietly win over the
            // gap that was just chosen: editconf takes -box over -d.
            if (String(node.params.box || '').trim()) {
              Editor.setParam(node, 'box', '', `box sides on ${node.title}`);
            }
            UI.toast(`${state.type}, ${state.distance.toFixed(2)} nm gap `
              + `-- about ${waters().toLocaleString()} waters`, 'ok');
          }
          return true;
        },
      },
    ]);
  },

  /* ------------------------------------------------- what is in a structure */

  /* The chain table you would otherwise open the file elsewhere to read.

     Ticking rows and pressing "Keep ticked chains" writes them into the node
     you asked from, which is the whole point: the question is only ever asked
     because something downstream needs the answer typed into it. */
  structureInfo(data, node) {
    const def = (App.defs[node && node.type] || {});
    const params = (def.params || []).map((p) => p.name);
    const canChains = params.includes('chains');
    const canHetero = params.includes('keep_hetero');

    const body = UI.el('div');
    const head = [
      `${data.n_atoms.toLocaleString()} atoms`,
      data.models > 1 ? `${data.models} models` : null,
      data.waters ? `${data.waters.toLocaleString()} waters` : null,
      data.ions ? `${data.ions.toLocaleString()} ions` : null,
    ].filter(Boolean).join(' · ');
    if (data.title) body.appendChild(UI.el('div', { class: 'hint', text: data.title }));
    body.appendChild(UI.el('div', { class: 'hint', text: head }));

    const real = data.chains.filter((c) => c.id !== '_');
    const boxes = new Map();

    if (real.length) {
      const table = UI.el('table', { class: 'info-table' });
      table.appendChild(UI.el('tr', {}, [
        UI.el('th', { text: '' }), UI.el('th', { text: 'chain' }),
        UI.el('th', { text: 'what' }), UI.el('th', { text: 'residues' }),
        UI.el('th', { text: 'numbered' }), UI.el('th', { text: 'contains' }),
      ]));
      // What the node was last told to keep, if anything. Opening this dialog
      // on a node that already has a chain list used to start again from
      // "every protein chain", so a set chosen by hand looked as though it had
      // never been applied -- and applying again quietly widened it.
      const already = new Set(String((node && node.params && node.params.chains) || '')
        .split(/[\s,]+/).filter(Boolean));
      for (const chain of data.chains) {
        const tick = UI.el('input', { type: 'checkbox' });
        tick.checked = already.size ? already.has(chain.id) : chain.kind === 'protein';
        boxes.set(chain.id, tick);
        // What is worth reading differs by chain. For a protein chain with a
        // ligand or waters stuck to it, the split is the useful thing; for a
        // chain of ligands or lipids it is the names.
        const parts = Object.entries(chain.breakdown || {});
        const names = chain.resnames.join(' ')
          + (chain.distinct > chain.resnames.length
            ? ` +${chain.distinct - chain.resnames.length}` : '');
        const contains = chain.kind === 'other' || parts.length === 1
          ? names : parts.map(([kind, n]) => `${n.toLocaleString()} ${kind}`).join(' + ');
        const row = UI.el('tr', chain.molecule ? { title: chain.molecule } : {}, [
          UI.el('td', {}, [tick]),
          UI.el('td', { text: chain.id === '_' ? '(none)' : chain.id }),
          UI.el('td', { class: `kind-${chain.kind}`, text: chain.kind }),
          UI.el('td', { text: chain.residues.toLocaleString() }),
          UI.el('td', { text: `${chain.first}–${chain.last}` }),
          UI.el('td', { class: 'contains', text: contains }),
        ]);
        row.addEventListener('click', (event) => {
          if (event.target !== tick) tick.checked = !tick.checked;
        });
        table.appendChild(row);
      }
      body.appendChild(table);

      /* Twelve chains in a receptor complex are six molecules, and the
         question this dialog exists to answer -- which letters do I keep --
         is answered by the shorter list. So it goes below the table, one line
         per molecule, rather than as a sixth column repeating the same
         sentence four times. Clicking a line ticks its chains. */
      const molecules = data.molecules || [];
      if (molecules.length) {
        body.appendChild(UI.el('div', { class: 'field-label', text:
          molecules.length === 1 ? 'what it is' : 'what the chains are' }));
        const list = UI.el('table', { class: 'info-table' });
        for (const molecule of molecules) {
          const letters = molecule.chains.join(', ');
          const line = UI.el('tr', {
            title: `tick ${letters}`,
          }, [
            UI.el('td', { class: 'chain-letters', text: letters }),
            UI.el('td', { text: molecule.description }),
          ]);
          line.style.cursor = 'pointer';
          line.addEventListener('click', () => {
            // Whether it ticks or unticks depends on where they already are,
            // so a second click undoes the first rather than doing nothing.
            const ticks = molecule.chains.map((id) => boxes.get(id)).filter(Boolean);
            const already = ticks.every((t) => t.checked);
            for (const t of ticks) t.checked = !already;
          });
          list.appendChild(line);
        }
        body.appendChild(list);
      }
    } else {
      body.appendChild(UI.el('div', { class: 'hint', text:
        'No chain identifiers in this file — GROMACS writes none, and a .gro has '
        + 'nowhere to put them. What it holds is below.' }));
    }

    const species = data.species.filter((sp) => sp.kind !== 'water');
    if (species.length) {
      body.appendChild(UI.el('div', { class: 'field-label', text:
        `molecules (${data.n_species} kinds)` }));
      const table = UI.el('table', { class: 'info-table' });
      for (const sp of species.slice(0, 30)) {
        table.appendChild(UI.el('tr', {}, [
          UI.el('td', { text: sp.name }),
          UI.el('td', { class: `kind-${sp.kind}`, text: sp.kind }),
          UI.el('td', { text: sp.residues.toLocaleString() }),
        ]));
      }
      body.appendChild(table);
    }

    const ticked = () => [...boxes.entries()].filter(([, t]) => t.checked)
      .map(([id]) => id).filter((id) => id !== '_');

    const buttons = [{ label: 'Close' }];
    if (node) {
      // The other half of the question, and the one that decides whether
      // anything needs rebuilding before this goes near a force field.
      buttons.push({ label: 'What is missing?',
                     action: () => { App.inspectMissing(node.id); return false; } });
    }
    // Nothing to copy when the format has nowhere to put a chain letter.
    if (real.length) {
      buttons.push({
        label: 'Copy chain letters',
        action: () => { UI.copy(ticked().join(',')); return false; },
      });
    }
    if (canChains && real.length) {
      buttons.push({
        label: 'Keep ticked chains',
        primary: true,
        action: () => {
          const value = ticked().join(',');
          node.params.chains = value;
          Editor.mark(`keep chains on ${node.title}`);
          Editor._refreshNodeElement(node);
          Editor.changed();
          UI.toast(value ? `keeping chains ${value}` : 'keeping every chain', 'ok');
        },
      });
    }
    if (canHetero && data.hetero.length) {
      buttons.splice(1, 0, {
        label: 'Keep these heteroatoms',
        action: () => {
          const value = data.hetero.map((h) => h.name).join(',');
          node.params.keep_hetero = value;
          Editor.mark(`keep heteroatoms on ${node.title}`);
          Editor._refreshNodeElement(node);
          Editor.changed();
          UI.toast(`keeping ${value}`, 'ok');
        },
      });
    }
    UI.modal(data.name || 'structure', body, buttons);
  },

  /* ------------------------------------------- what is *not* in a structure */

  /* The deposited sequence with the holes drawn into it.

     A REMARK block tells you a number. Seeing the run sitting between two
     resolved stretches tells you whether it is a loop with both ends pinned or
     a tail hanging off an end, and that is the decision this exists to support
     -- one has a constrained answer and the other is a guess wearing
     coordinates. Click a run to take all of it; drag across one to take part.
     Ticking writes the regions into the node that asked. */
  /* A name cut to fit, keeping both ends of it. */
  shorten(text, limit) {
    if (text.length <= limit) return text;
    const tail = Math.floor((limit - 1) * 0.55);
    return `${text.slice(0, limit - 1 - tail)}…${text.slice(-tail)}`;
  },

  missingResidues(data, node) {
    const def = (App.defs[node && node.type] || {});
    const params = (def.params || []).map((p) => p.name);
    const canOnly = params.includes('only');
    const chains = data.chains || [];

    /* gap id -> [firstPosition, lastPosition] of what will actually be built,
       in offsets along the chain. Ranges, not a bare set of ids, because part
       of a tail is a real answer -- see anchored() for why part of a loop is
       not. */
    const picked = new Map();
    const blocks = new Map();
    const gapsById = new Map();
    const chainOfGap = new Map();
    for (const chain of chains) {
      for (const gap of chain.gaps) {
        gapsById.set(gap.id, gap);
        chainOfGap.set(gap.id, chain);
      }
    }

    /* Nothing is ticked to start with. It used to open with every internal gap
       already chosen, which is a fair guess for a single-chain structure and
       wrong for anything bigger: a deposited structure can hold a complex and its
       copy, sixteen chains, and somebody who wanted the eight upper-case ones had
       to untick the other eight before they could start. A dialog for choosing should
       not arrive having chosen.

       The button below puts the old default back in one click, and honours the
       node's own chain list while it does -- which is the answer to that case
       rather than a workaround for it. */
    const chainFilter = new Set(
      String(((node && node.params) || {}).chains || '')
        .split(',').map((c) => c.trim()).filter(Boolean));
    const inScope = (chain) => !chainFilter.size || chainFilter.has(chain.id);
    const internalGaps = () => chains.filter(inScope)
      .flatMap((chain) => chain.gaps)
      .filter((gap) => gap.kind === 'internal' && gap.known);

    function span(gap) { return [gap.position - 1, gap.position - 1 + gap.length - 1]; }

    /* What a selection of part of a gap really means.

       An internal gap is pinned at both ends, so any part of it means all of
       it: build half and the two halves of the chain are still bonded across
       what is left, and the optimiser pulls them shut. A tail has one anchor
       and grows away from it, so selecting a piece builds from the anchor out
       to the far end of that piece -- anything else leaves a fragment
       floating off the end of the chain. */
    function anchored(gap, from, to) {
      const [first, last] = span(gap);
      if (gap.kind === 'internal') return [first, last];
      if (gap.kind === 'n-term') return [Math.max(from, first), last];
      return [first, Math.min(to, last)];
    }

    const label = (chain, index) => {
      const value = chain.numbers[index];
      return value === null || value === undefined ? null : value;
    };
    const spec = (gap) => {
      const chain = chainOfGap.get(gap.id);
      const [lo, hi] = picked.get(gap.id);
      const a = label(chain, lo);
      const b = label(chain, hi);
      return a === null || b === null
        ? `${chain.id}#${lo + 1}..${hi + 1}` : `${chain.id}:${a}..${b}`;
    };
    const chosen = () => [...picked.keys()].map((id) => spec(gapsById.get(id)));

    const fasta = () => chains.map((chain) =>
      `>${(data.name || 'structure').replace(/\.[^.]+$/, '')}_${chain.id}\n`
      + (chain.letters.match(/.{1,60}/g) || []).join('\n')).join('\n') + '\n';

    const toggle = (gap) => {
      if (!gap.known) {
        UI.toast(`${gap.id}: the file does not say which residues these are, so `
          + 'nothing can build them', 'warn', 8000);
        return;
      }
      if (picked.has(gap.id)) picked.delete(gap.id); else picked.set(gap.id, span(gap));
      render();
    };

    /* --------------------------------------------------------- the sequence */

    const WIDTH = 60;
    let drag = null;

    const gapMap = (chain) => {
      const at = new Array(chain.letters.length).fill(null);
      for (const gap of chain.gaps) {
        for (let i = gap.position - 1; i < gap.position - 1 + gap.length; i += 1) at[i] = gap;
      }
      return at;
    };

    /* Which residue is under the pointer. One span per run of the same state
       keeps a 600-residue chain at ten elements a row instead of six hundred,
       and the font is monospace, so the offset within a run is arithmetic. */
    const residueAt = (event) => {
      // From the pointer position, not from event.target: the listener that
      // tracks a drag is on the window, so its target is wherever the mouse
      // happens to be, which during a drag is usually not the run it started on.
      const under = document.elementFromPoint(event.clientX, event.clientY);
      const el = under && under.closest ? under.closest('.res') : null;
      if (!el) return null;
      const start = Number(el.dataset.start);
      const count = Number(el.dataset.count);
      const box = el.getBoundingClientRect();
      const step = box.width / count;
      const offset = Math.min(count - 1, Math.max(0,
        Math.floor((event.clientX - box.left) / (step || 1))));
      return { chain: el.dataset.chain, index: start + offset };
    };

    const paintDrag = (event) => {
      const hit = residueAt(event);
      if (!hit || !drag || hit.chain !== drag.chain || hit.index === drag.to) return;
      drag.to = hit.index;
      drawSequence(chains.find((c) => c.id === drag.chain));
    };

    /* Bound on the window, not the row: the pointer leaves the sequence long
       before the drag is finished, and a mouseup outside it still ends one. */
    const beginDrag = (event, host) => {
      if (event.button !== 0) return;
      const hit = residueAt(event);
      if (!hit) return;
      event.preventDefault();
      drag = { chain: hit.chain, from: hit.index, to: hit.index };
      const track = (move) => paintDrag(move);
      const finish = () => {
        window.removeEventListener('mousemove', track);
        window.removeEventListener('mouseup', finish);
        endDrag();
      };
      window.addEventListener('mousemove', track);
      window.addEventListener('mouseup', finish);
    };

    const endDrag = () => {
      if (!drag) return;
      const { chain, from, to } = drag;
      drag = null;
      const record = chains.find((c) => c.id === chain);
      const lo = Math.min(from, to);
      const hi = Math.max(from, to);
      const at = gapMap(record);
      const touched = new Set();
      for (let i = lo; i <= hi; i += 1) if (at[i]) touched.add(at[i]);
      if (!touched.size) { render(); return; }
      // Ending where it started is a click, whatever the mouse did in between.
      if (lo === hi) { toggle([...touched][0]); return; }
      for (const gap of touched) {
        if (!gap.known) continue;
        picked.set(gap.id, anchored(gap, lo, hi));
      }
      render();
    };

    const drawSequence = (chain) => {
      const host = blocks.get(chain.id);
      if (!host) return;
      const at = gapMap(chain);
      const dragLo = drag && drag.chain === chain.id ? Math.min(drag.from, drag.to) : -1;
      const dragHi = drag && drag.chain === chain.id ? Math.max(drag.from, drag.to) : -2;
      const state = (index) => {
        const gap = at[index];
        if (!gap) return index >= dragLo && index <= dragHi ? 'res over' : 'res';
        const range = picked.get(gap.id);
        const on = range && index >= range[0] && index <= range[1];
        return `res gap ${gap.kind}${on ? ' picked' : ''}`
          + (index >= dragLo && index <= dragHi ? ' over' : '');
      };
      host.innerHTML = '';
      for (let start = 0; start < chain.letters.length; start += WIDTH) {
        const end = Math.min(start + WIDTH, chain.letters.length);
        const row = UI.el('div', { class: 'seq-row' });
        row.appendChild(UI.el('span', { class: 'seq-num', text: number(chain, start) }));
        const line = UI.el('span', { class: 'seq-line' });
        let index = start;
        while (index < end) {
          const cls = state(index);
          let stop = index;
          while (stop < end && state(stop) === cls) stop += 1;
          const gap = at[index];
          line.appendChild(UI.el('span', {
            class: cls,
            text: chain.letters.slice(index, stop),
            'data-chain': chain.id,
            'data-start': String(index),
            'data-count': String(stop - index),
            title: gap
              ? `${gap.id} — ${gap.kind}, ${gap.length} residues. Click for all of it, `
                + 'drag to take part.'
              : '',
          }));
          index = stop;
        }
        row.appendChild(line);
        row.appendChild(UI.el('span', { class: 'seq-num right', text: number(chain, end - 1) }));
        host.appendChild(row);
      }
    };

    const number = (chain, index) => {
      const value = chain.numbers[index];
      return value === null || value === undefined ? `#${index + 1}` : String(value);
    };

    /* ------------------------------------------------------------- drawing */

    const body = UI.el('div');
    const render = () => {
      body.innerHTML = '';
      blocks.clear();
      const head = [];
      if (data.source) head.push(`read from ${data.source}`);
      if (data.fetched) head.push('fetched and kept');
      if (head.length) body.appendChild(UI.el('div', { class: 'hint', text: head.join(' · ') }));
      for (const warning of data.warnings || []) {
        body.appendChild(UI.el('div', { class: 'hint warned', text: warning }));
      }
      if (!chains.length) {
        body.appendChild(UI.el('div', { class: 'hint', text:
          'No protein or nucleic chain to read a sequence from.' }));
        return;
      }
      const missing = chains.reduce((n, c) => n + c.missing, 0);
      const total = chains.reduce((n, c) => n + c.length, 0);
      // With nothing but the numbering to go on there is no deposited sequence
      // to be complete against, so "nothing is missing" would overclaim.
      const bare = data.source === 'residue numbering';
      body.appendChild(UI.el('div', { class: 'hint', text: missing
        ? `${missing} of ${total} residues were never resolved`
        : (bare
          ? `${total} residues, with no jumps in the numbering — but this file carries `
            + 'no sequence to compare against, so a missing tail would not show'
          : `nothing is missing — all ${total} residues of the deposited sequence are here`) }));
      if (missing && canOnly) {
        body.appendChild(UI.el('div', { class: 'hint', text:
          'Nothing is ticked yet. Click a coloured run to take all of it, or drag '
          + 'across one to take part. Part of a tail is built from the residue it '
          + 'hangs off; part of a loop is the whole loop, because half a loop would '
          + 'be pulled shut.' }));
      }

      for (const chain of chains) {
        body.appendChild(UI.el('div', { class: 'field-label' }, [
          'chain ',
          // Outside the label's own text, because the label is uppercased and
          // a chain id is case-significant: a structure can hold one complex as
          // A..N and its copy as a..n, and uppercasing turns sixteen chains into
          // eight listed twice.
          UI.el('span', { class: 'literal', text: chain.id }),
          // What it is, beside what it is called. Shortened rather than
          // wrapped: the numbers after it are the reason this line exists,
          // and a full deposited name would push them onto a second row.
          //
          // Elided in the middle, not at the end. A deposited name puts the
          // boilerplate first and the identity last -- cutting the tail off
          // "Immunoglobulin heavy chain variable region 3" throws away the
          // only part that tells it from the chain above it.
          chain.molecule
            ? UI.el('span', { class: 'literal molecule', title: chain.molecule,
                text: ` ${Panels.shorten(chain.molecule, 48)}` })
            : null,
          ` · ${chain.kind} · ${chain.length} residues`
          + (chain.missing ? ` · ${chain.missing} missing`
             + ` (${Math.round(100 * chain.missing / chain.length)}%)` : ' · complete')
          + (chain.first === null ? '' : ` · numbered ${chain.first}–${chain.last}`),
        ]));
        const host = UI.el('div', { class: 'seq' });
        host.addEventListener('mousedown', (event) => beginDrag(event, host));
        blocks.set(chain.id, host);
        body.appendChild(host);
        drawSequence(chain);
        if (!chain.gaps.length) continue;

        const table = UI.el('table', { class: 'info-table' });
        table.appendChild(UI.el('tr', {}, [
          UI.el('th', { text: '' }), UI.el('th', { text: 'region' }),
          UI.el('th', { text: 'where' }), UI.el('th', { text: 'residues' }),
          UI.el('th', { text: 'building' }), UI.el('th', { text: 'sequence' }),
        ]));
        for (const gap of chain.gaps) {
          const tick = UI.el('input', { type: 'checkbox' });
          tick.checked = picked.has(gap.id);
          tick.disabled = !gap.known;
          tick.addEventListener('change', () => toggle(gap));
          const range = picked.get(gap.id);
          const building = !range ? '—'
            : (range[1] - range[0] + 1 === gap.length ? 'all of it'
              : `${range[1] - range[0] + 1} of ${gap.length}, ${spec(gap)}`);
          const row = UI.el('tr', {}, [
            UI.el('td', {}, [tick]),
            UI.el('td', { text: gap.id }),
            UI.el('td', { class: `gap-${gap.kind}`, text: gap.kind }),
            UI.el('td', { text: String(gap.length) }),
            UI.el('td', { class: range ? 'kind-protein' : 'muted', text: building }),
            UI.el('td', { class: 'contains', text: gap.known
              ? (gap.sequence.length > 40 ? `${gap.sequence.slice(0, 37)}…` : gap.sequence)
              : 'not named in the file' }),
          ]);
          row.addEventListener('click', (event) => { if (event.target !== tick) toggle(gap); });
          table.appendChild(row);
        }
        body.appendChild(table);
      }
    };
    render();

    const buttons = [{ label: 'Close' }];
    if (canOnly && internalGaps().length) {
      const scope = chainFilter.size
        ? ` in ${[...chainFilter].join(', ')}`
        : '';
      buttons.push({
        label: `Tick every internal gap${scope}`,
        action: () => {
          const wanted = internalGaps();
          const already = wanted.every((gap) => picked.has(gap.id));
          for (const gap of wanted) {
            if (already) picked.delete(gap.id); else picked.set(gap.id, span(gap));
          }
          render();
          return false;
        },
      });
    }
    buttons.push({
      label: 'Copy the full sequence',
      action: () => { UI.copy(fasta()); return false; },
    });
    // Same again: this is reached from "What is in this file?", where the
    // chain ticks are the whole point and are held nowhere but on screen.
    const title = `What is missing from ${data.name}`;
    if (UI.modalOpen()) UI.subModal(title, body, buttons, { wide: true });
    else UI.modal(title, body, buttons);
  },

  /* ---------------------------------------------------------------- help */
  /* Thirty sections is a book, and a book with no contents page is a scroll.
     The list down the side is built from the headings themselves, so it cannot
     drift from what is under it, and typing in the box hides every section
     that does not match -- which is how you find "maxwarn" without knowing
     that it lives under Running. */
  /* The table of file kinds in Help, from the same FILE_GUIDE the sockets
     explain themselves with, each beside the colour its wires are drawn in. */
  _fileGuideTable() {
    const guide = Editor.fileGuide || {};
    const safe = (text) => String(text).replace(/&/g, '&amp;')
      .replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const rows = Object.entries(guide)
      .filter(([key]) => key !== 'file')
      .map(([key, entry]) => '<tr><th>'
        + `<span class="help-swatch" style="background:${PORT_COLORS[key] || PORT_COLORS.file}"></span>`
        + `${safe(entry.name)}<br><code>${safe(entry.endings)}</code></th>`
        + `<td>${safe(entry.what)}</td></tr>`);
    return rows.length
      ? `<table class="help-files">${rows.join('')}</table>`
      : '<p>The list has not arrived from the server yet. Open Help again in a moment.</p>';
  },

  help() {
    const body = UI.el('div', { class: 'help-page' });
    const article = UI.el('article');
    body.appendChild(UI.el('nav', { class: 'help-toc' }));
    body.appendChild(article);
    article.innerHTML = `
      <h2>Files</h2>
      <h3>The kinds of file, and what is in them</h3>
      <p>Every wire carries a file from the block that makes it to the blocks that
      use it, and its colour says which kind of file that is. <b>Point at any socket,
      or at a dot on a box's wall,</b> to read what it carries. Here are all of
      them.</p>
      ${this._fileGuideTable()}
      <h2>The graph</h2>
      <h3>Working with the graph</h3>
      <table>
        <tr><th>Add a node</th><td>Click it in the palette, drag it onto the canvas, or right-click the canvas.</td></tr>
        <tr><th>Build a chain</th><td>Select a node, then click the next block in the palette: it is placed beside the selected one and wired to it wherever an output and an input are the same kind of file. Click, click, click.</td></tr>
        <tr><th>Tidy</th><td>Pushes apart any nodes sitting on top of each other, column by column, without changing what feeds what. <b>T</b> does the same.</td></tr>
        <tr><th>Connect</th><td>Drag from an output dot to an input dot. Wire colours follow the data type.</td></tr>
        <tr><th>Disconnect</th><td>Four ways, and they all undo with <b>Ctrl+Z</b>. Double-click the dot on the left of the block that is receiving the wire. Drag the wire off that dot and let go over empty canvas. Right-click the wire and choose <i>Remove link</i>. Or hold <b>Ctrl</b> and right-click the wire, which cuts it there and then with no menu (on a Mac hold <b>Cmd</b>, because there Ctrl and click is how you ask for a menu). You do not have to land on the line itself: a band about 14 pixels wide counts as being on it, and the wire thickens to show which one you are about to cut.</td></tr>
        <tr><th>Moving the canvas</th><td>Hold <b>space</b> and drag. That one works on a mouse, a trackpad or a tablet. The middle mouse button drags it too. On a laptop, set <i>What you are pointing with</i> in Settings to Trackpad and two fingers slide the canvas instead of zooming it. Dragging empty canvas draws a selection box, it does not move the view.</td></tr>
        <tr><th>Zoom</th><td>The wheel, or pinch on a trackpad, or Ctrl and the wheel. <b>F</b> fits the whole graph on screen.</td></tr>
        <tr><th>Select</th><td>Click, shift-click, or drag a box on empty canvas.</td></tr>
        <tr><th>Find one</th><td><b>Ctrl + F</b> searches this graph — titles, types, and the values inside the nodes, so "which node points at that tpr" is answerable. The palette box up on the left searches the catalogue instead.</td></tr>
        <tr><th>Move freely</th><td>Hold <b>Ctrl</b> while dragging to bypass the 8&nbsp;px grid snap.</td></tr>
      </table>
      <h3>Groups</h3>
      <p>Select some nodes and press <b>Ctrl+G</b> to wrap them in a coloured box with a
      name on it. Drag the title bar to move the box and everything in it; drag the
      corner to resize; double-click the title to rename. Right-click the title bar for
      a row of colour swatches, <i>Fit to contents</i>, <i>Select contents</i>, and
      <i>Save as chunk</i>.</p>
      <p><b>A chunk's two walls are a patch panel.</b> Think of the board at the back
      of a rack: cables come to it from all over, each gets a labelled socket, and short
      leads run from those sockets to wherever they are needed. Nothing is on a wall
      until you put it there.</p>

      <p>To put something on a wall, drag a wire out of any socket that produces
      something and let it go on a <b>dashed circle</b>: one at the top of the left
      wall, one at the bottom of the right wall. What that wire carries gets its own
      named dot on that wall. Then drag from that dot to whatever needs it, as many
      times as you like. The left wall fills downwards and the right wall upwards, which
      keeps the names away from the top right of the blocks inside, where their own
      outputs are.</p>

      <p><b>Double-click an output socket</b> to put what it carries straight onto the
      right-hand wall of its box, the way out of a chunk, without dragging anything. The
      same double-click takes it off again, and one on the left wall moves across.</p>

      <p>Until you wire something from it, a cable on a wall is drawn as a <b>dashed
      line</b> from its block to its dot, so you can always see where it comes from.
      A dot stands for the wires going through it: <b>cut the last of them and the dot
      comes off the wall too</b>, and Ctrl+Z puts back both. Picking a wire up by its
      end leaves the dot alone until you let go. To take off a cable nothing is wired
      from yet, right-click its dashed line.</p>

      <p><b>Wiring one block straight to another still works</b> and is still drawn as a
      straight wire between the two. A wall is somewhere to route a cable when you want
      the picture tidier, not a gate everything has to go through.</p>

      <p>Neither wall is the in wall or the out wall, and neither is for a particular
      kind of file. Both take anything, and it is your choice which side a cable comes
      out of. Letting the same cable go on the other wall moves it across instead
      of making a second copy. Only something that produces a file goes on a wall: a
      wire dragged backwards out of a socket waiting to be fed has nothing behind it to
      hang there.</p>

      <p><b>Wires run left to right through a wall, as they do through a block.</b> A
      cable that leaves its box through the right wall sets off to the right, and one
      that comes into a box through the left wall arrives from the left. So a cable going
      to a box underneath runs out to the right, round through the gap between the two
      boxes and in from the left, instead of cutting back across the box it has just
      left. When several cables make that trip together, they wrap round the corners
      like a bundle: the one nearest the corner turns tightest, and each one further out
      swings a little wider, so they never cross. A cable you put on the other wall,
      leaving through the left or arriving through the right, bends whichever way is
      shorter.</p>

      <p><b>Each cable is named beside its dot</b>, as shortly as it can be and still
      say which one it is. Usually that is just what comes out of the socket, such as
      <i>trajectory</i> or <i>tpr</i>. If two on the same box would read the same, both
      are given the block they come from instead. If that still reads the same, they get
      both and then a number. A cable nothing could be confused with keeps its short
      name even while the ones beside it are being lengthened.</p>

      <p>The names are written <b>outside the box</b>, so they cover nothing of the
      chunk itself. The one exception is another box standing right against that wall,
      where the name goes back inside rather than over somebody else's chunk. Either way
      it sits on a small solid tab, is cut short if it is very long, and opens out in
      full when you point at it.</p>

      <p>Right-click a dot to rename it something of your own, to take it off the wall
      and leave its wires drawn straight, or to take it off and cut them.</p>

      <p>A cable on a wall is not a new kind of link. The dot stands for a socket on a
      block inside, and drawing a wire from it draws exactly the link you would have
      drawn by hand. All that is kept with the box is a note of which cables you routed
      and which wall you chose, and that note only ever decides how a wire is drawn. The
      run order, the problems list and the generated scripts know nothing about
      walls.</p>

      <p><b>Inputs</b>, in a group's right-click menu, lists everything that
      chunk needs from outside itself in one window: the files it reads from disk,
      the sockets fed by blocks elsewhere in the graph, and the ones still waiting
      for something. Each row does exactly what changing it in the block would do,
      so a chunk can be pointed at a different structure, or joined to a different
      run, without opening the blocks inside it one at a time. The blocks are
      unchanged and still work the way they always did; this is a shorter way to
      the same edits, not a new one. Optional sockets that nearly every graph
      leaves empty are behind a tick box so they do not bury the one or two that
      matter. The same window is on the group's right-click menu.</p>

      <p>A group is organisational only — nothing about one changes what runs. What is
      inside it is simply whatever is standing in its bounds, so dragging a node in puts
      it in and dragging it out takes it out.</p>
      <p>The shipped workflows and the packaged tutorials use one colour convention:
      <b>green</b> structure in, <b>olive</b> box/solvent/ions or an ice crystal,
      <b>teal</b> minimisation, <b>blue</b> equilibration, <b>purple</b> production,
      <b>brown</b> analysis, <b>grey</b> shared settings.</p>
      <h3>Chunks and tutorials</h3>
      <p>A chunk is a piece of graph — a few nodes already wired together, inside a
      coloured box. Click one to drop it in the middle of the view, or drag it to put
      it where you want it.</p>
      <p>Tutorials work the same way. Clicking one opens its panel: what it needs,
      which of those tools are installed here, the steps with links to the original
      pages, and the citation. From there, <b>Load as new graph</b> replaces the canvas
      and keeps the step list working, while <b>Add to canvas</b> puts it beside what is
      already there. Dragging a tutorial straight onto the canvas does the second one,
      where you dropped it.</p>
      <h3>Custom chunks</h3>
      <p>Select nodes, right-click, <b>Save selection as a chunk…</b>. It appears in the
      palette under <b>Custom chunks</b>, and the <i>Section</i> box is a heading of your
      own — leave it blank or type one, and chunks sharing a section are listed under
      it.</p>
      <p>Parameters are saved exactly as they stand, so set what you want the chunk to
      start from <i>before</i> saving it. Any coloured group whose contents are entirely
      inside the selection comes along too. Each chunk is one file in
      <code>~/.comfy-gmx/chunks/</code>; hover a chunk to see its path, and the
      <b>×</b> on it deletes it.</p>
      <h3>Undo</h3>
      <p>Ctrl+Z steps back through anything that changed the graph: adding and deleting
      nodes, wiring and unwiring, moving, editing a parameter, dropping in a chunk,
      opening a workflow over the one you had. The buttons in the toolbar name what they
      will undo, so you can see where you are before you press.</p>
      <p>One action is one step even when it touched many nodes: deleting five nodes,
      or loading a seventy-node tutorial, comes back in a single press. Undoing a delete
      brings the wires and the selection back with the nodes.</p>
      <p>Each session has its own history, and Ctrl+Z inside a text box is the browser's
      own undo for that box, not the graph's. History lives for as long as the tab does;
      it is not saved with the workflow.</p>
      <h3>Opening and saving</h3>
      <p><b>Open</b> lists workflows from more than one place: the folder <b>Save</b>
      writes to, the examples that ship with Comfy-gmx, the packaged tutorials, and any
      folder you add under <i>Settings &rarr; Workflow folders</i>. Each group shows its
      path. The shipped ones are read-only — open one, change it, and Save keeps your
      version separate under your own folder.</p>
      <p><b>Browse…</b> opens any <code>.json</code> from anywhere on disk, which is what
      you want for a workflow kept next to the data it produced.</p>
      <h3>Sessions</h3>
      <p>The bar under the toolbar holds one tab per session. A session is a workflow
      with its own graph, its own output folder and its own run, and they run at the
      same time — start one, switch to another, start that too. Double-click a tab to
      rename it.</p>
      <p>A run you switch away from keeps going and keeps reporting: its tab shows a
      coloured dot, its log is still there when you come back, and it tells you when it
      finishes or fails. Runs live on the server, not in the page, so closing a tab or
      reloading does not stop them — a reload reattaches to whatever is still going.</p>
      <h3>Keyboard</h3>
      <table>
        <tr><th>Ctrl + Enter</th><td>Run the whole graph</td></tr>
        <tr><th>Ctrl + Shift + Enter</th><td>Run the selected nodes and their inputs</td></tr>
        <tr><th>Ctrl + S / Ctrl + O</th><td>Save / open a workflow</td></tr>
        <tr><th>Ctrl + Shift + N</th><td>New session</td></tr>
        <tr><th>Ctrl + Tab</th><td>Next session (add Shift for the previous one)</td></tr>
        <tr><th>Ctrl + Z</th><td>Undo</td></tr>
        <tr><th>Ctrl + Shift + Z</th><td>Redo (Ctrl + Y works too)</td></tr>
        <tr><th>Ctrl + F</th><td>Find a node in this graph — by title, by type, or by a value in it. Enter steps through the matches, Shift + Enter goes back.</td></tr>
        <tr><th>Ctrl + G</th><td>Group the selection in a coloured box</td></tr>
        <tr><th>Ctrl + M</th><td>Switch the selection off, or back on. A switched-off block is left out of checking and running, and so is anything that depends on it.</td></tr>
        <tr><th>Double-click an output</th><td>Put it on the right-hand wall of its box, or take it off again. Double-clicking an input unplugs it.</td></tr>
        <tr><th>Ctrl + Alt + click</th><td>Switch one block off or back on. On a box's title bar, the whole chunk. Cmd + Option + click on a Mac.</td></tr>
        <tr><th>Ctrl + D</th><td>Duplicate the selection</td></tr>
        <tr><th>Delete</th><td>Remove the selection</td></tr>
        <tr><th>Escape</th><td>Close a dialog, close the find box, stop renaming a tab, or clear the selection</td></tr>
      </table>
      <h2>Files and folders</h2>
      <h3>The Files tab</h3>
      <p>Two views, and the button in its corner swaps them. <b>By node</b> is what a
      run produced, grouped under the node that produced it — the answer to "what did
      that just make". Each group names its work directory, with a button to copy that
      path and one to open the folder in the other view.</p>
      <p><b>Browse</b> walks the filesystem. Type or paste a path, or take one of the
      shortcuts — this run, the output folder, uploads, home. A file opens where it
      belongs when you click it: a structure in the Viewer, an .xvg in the Plot tab,
      anything else as text.</p>
      <p><b>Drag a file out onto the canvas</b> and it becomes the node that reads that
      kind of file, pointing at the file where it already is — nothing is copied, which
      is what makes it usable for a 15 GB trajectory. <b>Drop files onto the panel</b>
      and they are copied into the folder being shown, which is the one thing a node
      cannot do for you.</p>
      <p><b>+ folder</b> and <b>+ file</b> create them where you are standing. The pencil
      beside a small text file opens it in a plain editor — an mdp, an index file, a
      note next to a run. It appears only where it would work: past half a megabyte the
      editor would be showing you the start of a file and saving would throw the rest
      away, so it refuses rather than doing that.</p>
      <h3>Dropping files in</h3>
      <p>Drag a file from your file manager and let go <i>anywhere</i> in the window.
      A <code>.pdb</code> or <code>.gro</code> becomes a <b>Load structure</b> node; a
      <code>.top</code>, <code>.ndx</code>, <code>.xtc</code> or <code>.tpr</code>
      becomes a <b>Load file</b> with the type already set; an <code>.mdp</code> becomes
      a <b>Run parameters</b> node reading that file. Drop several at once and you get
      several nodes. Drop straight onto a file box on a node to fill in only that
      field.</p>
      <p>If the drag carries the real path — which is what a file manager sends — the
      node points at your original file and nothing is copied. That matters: a
      trajectory has no business being pushed through a browser. If your browser hides
      the path, as Chrome does, the file is copied into the uploads folder instead and
      the node points at the copy; past 64&nbsp;MB that is refused, and you should add a
      Load node and use its <b>…</b> button to point at the file where it already
      is.</p>
      <p>Dropping onto the <b>Files</b> panel means something different, and it is the
      one thing the canvas cannot do: the files are copied into the folder that panel
      is showing. A node points at a file; it never moves one.</p>
      <p>A workflow <code>.json</code> opens in a <i>new session</i>, so nothing you were
      working on is replaced. A link dragged from another tab becomes a <b>Download
      file</b> node.</p>
      <h3>Naming a session</h3>
      <p><b>Open folder</b>, next to the folder name on the right of the tab bar,
      shows that tab's folder in your desktop's own file manager. Before the tab has
      run anything that is the folder its runs will go in; afterwards it is the folder
      the last run wrote into. The button's tooltip says which. With no screen on the
      machine running the server there is nothing to open it with, so the path is
      copied to the clipboard instead.</p>

      <p><b>Double-click a tab</b> and its name becomes editable where it sits — Enter
      keeps it, Escape puts it back. <b>Right-click</b> one for the rest: rename,
      duplicate it to try something without risking what works, set its output folder,
      close it, or close all the others.</p>

      <h3>Output folder</h3>
      <p>The button on the right of the session bar sets where <i>this session</i>
      creates its run directories; each run gets a timestamped subfolder under it.
      Trajectories are large, so this is where you point at a scratch disk.</p>
      <p>It browses rather than asking you to type a path from memory: walk to the
      folder, or make one with <b>New folder…</b> where you are standing. The line
      underneath follows you, saying whether the folder is there and how much room is
      left on that disk, so a scratch disk with 40 GB free is something you find out
      before the run rather than during it. <b>Use default</b> hands it back to
      <b>Settings → Default output folder</b>, which has the same picker.</p>
      <h3>Seeing a structure in the graph</h3>
      <p>The <b>Preview structure</b> node draws whatever is wired into it, inside the
      node. Put one after a build step and the system appears there as soon as that part
      of the run finishes. It hands the structure straight on, so you can insert one in
      the middle of a chain without changing what the chain does.</p>
      <p>Drag inside the picture to turn it, shift-drag to slide it, scroll to zoom,
      double-click to reset. Drag the corner of the node to make it bigger, and use
      <b>⤢</b> to throw it into the Viewer tab at full size. Style and colour are display
      settings, not parameters — changing them never re-runs anything.</p>
      <p>Set the node's own <i>Or a file</i> box and it draws that file straight away,
      with nothing wired in and nothing run.</p>
      <p><b>⤓</b> on the node — and in the Viewer tab — offers two ways to keep it, and
      they are not the same thing. <i>Save</i> copies the file on the machine running
      Comfy-gmx, so a large structure never travels through the browser to reach a disk
      it is already on. <i>Download instead</i> hands it to your browser's download
      folder. To save as part of the run rather than by hand, use the <b>Save structure</b>
      node: it writes to a folder you choose every time the graph runs, and shows what
      it wrote.</p>
      <h2>Structures</h2>
      <h3>What is in a structure</h3>
      <p>Right-click any node that has a structure behind it and choose <b>What is in
      …</b>. It lists the chains with what each one is, how many residues it has and
      how they are numbered, then the molecule species. Nothing is run and nothing is
      written; a PDB id is fetched once and kept.</p>
      <p>Ask from the node that needs the answer. A <b>Clean structure</b> node has no
      file of its own, so the question follows the wires back to whatever is upstream —
      and the dialog can write the chains you tick straight into its <i>Keep chains</i>
      box, which is the reason you were asking.</p>
      <h3>What is missing from a structure</h3>
      <p>Right-click a node and choose <b>What is missing from …</b>: it reads the
      sequence the entry says it has — from <code>SEQRES</code> and
      <code>REMARK 465</code> in a <code>.pdb</code>, from
      <code>_pdbx_poly_seq_scheme</code> in an <code>.mmCIF</code> — and draws it
      with the holes in place. A hole is a stretch of the chain the experiment could
      not see, so the file has no coordinates for it.</p>
      <p>Holes are coloured by where they are.
      <span style="color:var(--warn)">Amber</span> is an <b>internal gap</b>: there is
      a resolved residue on each side of it. <span style="color:var(--error)">Red</span>
      is a <b>tail</b>: missing from one end of the chain.</p>
      <p><b>Copy the full sequence</b> gives you the sequence as FASTA, the plain-text
      format most sequence tools read. A <code>.gro</code> has nowhere to record a
      sequence that is not there, so ask this of the <code>.pdb</code> or
      <code>.cif</code> it came from.</p>
      <h2>Running</h2>
      <h3>Check</h3>
      <p><b>Check</b> plans every node without running anything and puts what it finds
      in the <b>Problems</b> tab. Click a row to select that node and bring it into
      view; the node itself turns red and carries the message.</p>
      <p>Only the nodes you have to fix are listed. A node that says
      <i>input 'tpr' is not connected</i> because the grompp above it could not produce
      one is a consequence, not a finding — those are outlined in dashed amber instead,
      and counted at the bottom of the list. The panel refreshes as you rewire, so you
      do not have to press Check again.</p>
      <p>An <i>optional</i> input left unconnected is not a problem, and the checker
      will not invent one.</p>
      <h3>Running</h3>
      <p>Every node runs in its own directory with its inputs staged in by name, so the
      command you see in the <b>Command</b> tab is the command that runs. Each node
      directory also contains <code>command.sh</code>, which you can run by hand.</p>
      <p>Nodes are content-addressed: a node whose parameters and upstream inputs have
      not changed is reused from a previous run instead of repeating the work. Use
      <i>Run this node only (ignore cache)</i> from the node menu to force it.</p>
      <h3>Switching blocks off</h3>
      <p>A block dropped in to try something and not wired up yet would stop the whole
      workflow from running, because its empty inputs are errors. <b>Switch it off</b>
      instead of deleting it: it stays where it is, wired as it was, and is left out of
      checking and running until you switch it back on.</p>
      <p><b>Ctrl + Alt + click</b> a block to switch it (Cmd + Option + click on a Mac),
      or select blocks and press <b>Ctrl + M</b>. Ctrl + Alt + click a box's title bar, or
      click the title and press Ctrl + M, to switch a whole chunk. The right-click menus
      of blocks and boxes have the same switch. If anything picked is still on, it all
      goes off; if it is all off, it all comes back on.</p>
      <p>A switched-off block is faded and striped with <b>OFF</b> on it. Anything that
      depends on it is left out too, drawn lighter with the reason written on it, because
      it cannot run without that file. The line beside Run counts both. Blocks that do
      run are remembered exactly as before, so their earlier results are still
      reused.</p>
      <h3>Presets, and what is in them</h3>
      <p>A run-parameters node starts from a preset — minimisation, NVT, NPT, production
      — and its widgets are <i>deltas</i>: blank means "whatever the preset says". Which
      was fine except that nothing said what the preset said, so thirteen boxes read
      "preset default" over a file of thirty options nobody could see. Each box now shows
      the preset's actual value as its placeholder: <code>5000000 (from lysozyme_md)</code>.</p>
      <p>Editing any of them changes what the node is claiming, so it stops claiming it.
      The mode switches from <b>preset</b> to <b>manual</b>, every other widget fills in
      with the preset's value — so what is on screen is the whole parameter set rather
      than one changed line over thirty invisible ones — and the file it writes is renamed
      after the preset it grew out of: <code>lysozyme_md_edited.mdp</code>. Downstream
      picks that up on its own, because grompp takes the file from the wire rather than by
      name.</p>
      <p>Changing the preset while editing refills from the new one but keeps anything you
      actually typed: swapping the baseline under a value you set yourself should not throw
      it away. Setting the mode back to <b>preset</b> empties the widgets and restores the
      stock file name.</p>

      <h3>Several nodes at once</h3>
      <p>A node starts as soon as everything it depends on has finished, and up to
      <b>Settings → Nodes at once</b> of them run together. A graph where four analyses
      hang off one trajectory used to run them one after another though they share
      nothing but their input; at the default of three that is now a third of the wall
      clock.</p>
      <p>Simulation nodes are exempt and run on their own. <code>mdrun</code> with
      <i>-ntomp</i> left at 0 takes every core it can see, so two at once is not twice
      the work — it is two runs fighting each other for the same cores. The scheduler
      waits for everything else to finish before starting one, and starts nothing else
      while it runs.</p>
      <p>Set it to 1 for strictly one node at a time, which is what it always did.</p>

      <h3>What Run will actually do</h3>
      <p>Beside the Run button is a line saying how much of the graph would really
      be computed — <i>3 of 50 will run · 47 reused · about 2 h</i> — and every node
      the run would take from the cache instead carries a dashed <b>cached</b> tag.
      It updates after every edit, on the same check that finds problems, because it
      costs a hash per node.</p>
      <p>The time is the median of what each <i>kind</i> of node has taken on this
      machine, not a guess from nowhere: how long a solvate takes here does not depend
      on which solvate it was. A node type that has never run here is counted
      separately — "plus 4 never timed here" — rather than being quietly left out of
      the total.</p>

      <h3>The node cache, and deleting runs</h3>
      <p>A node whose parameters and upstream inputs have not changed is reused from
      the run that produced it rather than run again. That is what makes changing one
      analysis parameter cost the analysis instead of the simulation, and it is why a
      re-run can finish in seconds.</p>
      <p>What is stored is an index — a few hundred kB of JSON saying "a node with this
      signature already ran, and its files are in that folder". The gigabytes are the
      run folders themselves. <b>Environments → Node cache</b> shows both numbers and
      offers to forget the index; forgetting it deletes no results and frees no disk,
      it only means everything runs again next time.</p>
      <p><b>Deleting a run folder is safe.</b> Every cache entry is re-checked when it
      is looked up — the folder has to still exist and so does every file it claims —
      and an entry that fails is dropped, so the node simply runs again. You cannot
      break a graph by deleting results.</p>
      <p><b>Runs…</b> in the Files tab lists every run folder with its size, how many
      node directories it has, how many cached results still point into it, and when it
      ran — tick the ones you do not need and delete them. It only ever deletes a
      directory that is named like a run and holds a <code>workflow.json</code>, so a
      mistyped path cannot remove anything else.</p>
      <p>One thing to know before you delete, though: when you re-run an unchanged
      graph, the cached nodes produce nothing new, so <i>that</i> run's folder holds a
      <code>workflow.json</code> and nothing else — the results are still in the older
      folder it reused. "Keep the newest, delete the old one" is therefore backwards.
      Sort by size instead: a run folder of a few kB is bookkeeping, and the large one
      is your data.</p>

      <h3>Setting a node up step by step</h3>
      <p>The <b>&#9881;</b> on a node's header — or <i>Set this up step by step</i> in its
      right-click menu — opens the same node with room around it. Every box has its
      explanation printed under it rather than hidden in a tooltip, the less usual
      settings are not folded away, a small table says what is plugged into each input
      and what is still missing, and the command that will run sits at the bottom and
      changes as you change the boxes.</p>
      <p>Two buttons at the foot run it: <i>Run just this node</i>, which reuses what the
      nodes before it produced last time, and <i>Run up to here</i>, which works back
      through everything feeding into it.</p>

      <h3>Boxes you can fill in with a form</h3>
      <p>Some boxes do not want a single value, they want a few lines in the language
      of whatever program the node runs — the answers a GROMACS tool would ask you for
      on the keyboard, or the energy terms to take out of a run. Those boxes
      carry a <b>Fill this in with a form…</b> button. The form asks the same thing
      with dropdowns and numbers, and shows the exact text it is about to write while
      you change it.</p>
      <p>Ten boxes have one: the answers a GROMACS tool reads from its keyboard,
      index groups and selections, energy terms, lists of files, and the rules for
      editing a text file. Opening a form on a box that already has
      something in it reads that back, including anything the form does not ask about,
      which is kept exactly as you typed it. The box itself stays editable throughout
      — if you know the words, typing them is still quicker.</p>

      <h3>Extra flags</h3>
      <p>Under <i>advanced</i>, a node that runs a command carries an <b>Extra flags</b>
      box named after it — <i>Extra flags for gmx grompp</i>. Whatever you type there is
      appended verbatim to that command, so an option Comfy-gmx does not model is never
      a dead end.</p>
      <p>Underneath the box is that command's own flag list: what each flag does, in one
      line, in the command's words rather than ours. Click one to add it. The flags the
      node already sets from its own widgets are listed too, greyed, and name the widget
      that owns them — GROMACS refuses a flag given twice, so those are the ones not to
      type.</p>
      <p>A node with no single command to append to — one that copies a file, writes a
      config, or draws a picture — has no such box, rather than one whose contents go
      nowhere. On the run-parameters node the same box takes raw <code>key = value</code>
      mdp lines instead, and on the Python node it takes arguments for your own script.</p>
      <h3>The terminal drawer</h3>
      <p><b>Terminal</b> at the bottom right of the canvas, or <b>Ctrl+&#96;</b>, opens a
      drawer under the graph with two tabs, <b>Run</b> and <b>Shell</b>. Drag its top edge
      to make it taller.</p>
      <p><b>Run</b> is a transcript of the run: every node in order, the command each one
      actually ran, its output and how it ended. The <b>Log</b> tab on the right shows one
      node at a time, which is what you want when reading a failure; this is what you want
      when the question is what it is doing now. It is a transcript, not a shell: what
      runs is what the graph says. The commands in it are copy-pasteable as they stand,
      and <b>Copy</b> takes the lot.</p>
      <p><b>Shell</b> is a real shell on this machine (bash), the same as a terminal
      window: <code>ls</code>, <code>cp</code>, <code>rm</code>, <code>nano</code>,
      <code>less</code>, <code>gmx</code>, anything you would type there. It starts in this
      tab's run folder, and <b>Go to run folder</b> takes it back there later. Ctrl+C stops
      the command that is running, as in any terminal; with text selected, Ctrl+C copies
      it instead, and Ctrl+V pastes. Reloading the page keeps the shell and what was on
      its screen. It ends when you type <code>exit</code>, or a minute after the page is
      closed; <b>New shell</b> starts a fresh one.</p>
      <p>A few keys belong to the browser and never reach the shell: Ctrl+W closes the
      browser tab, and Ctrl+T and Ctrl+N open new ones. In nano, search with F6 instead of
      Ctrl+W. While a command is running in the shell, the page asks before it is closed
      or reloaded.</p>
      <h3>From a terminal</h3>
      <p>Four scripts, and each answers <code>--help</code>:</p>
      <table>
        <tr><th><code>./start.sh</code></th><td>From a fresh clone: install what is missing, then open the editor. Every run after the first starts straight away.</td></tr>
        <tr><th><code>./run.sh</code></th><td>Just start the server. <code>--port 9000</code>, <code>--no-browser</code>.</td></tr>
        <tr><th><code>./setup.sh</code></th><td>The setup questions on their own, without starting anything.</td></tr>
        <tr><th><code>./install.sh</code></th><td>Optional: puts a <code>comfy-gmx</code> command on your PATH.</td></tr>
      </table>
      <p>Underneath them all is <code>python3 -m comfygmx</code>, which has more:
      <code>check</code> reports which tools it can reach, <code>nodes</code> lists the
      node types, and <code>run</code> executes a saved workflow with no browser at all
      — that is the one to put in a batch script.</p>
      <h2>Installing things</h2>
      <h3>Setting up a new machine</h3>
      <p><b>Set up</b> in the top bar — it appears whenever something is missing —
      installs what this machine has not got. conda goes into your home directory,
      then each tool into its own environment. Your shell startup files are left
      alone, because Comfy-gmx reaches that conda directly rather than through your
      PATH; there is a checkbox if you want it in your own terminal too.</p>
      <p>It never asks for your password. A system package that needs root — a
      compiler, cmake — is shown as one line for <i>your</i> distribution, to paste
      into a terminal where the prompt is visible. A button that hangs on an invisible
      sudo prompt would be worse than no button.</p>
      <p>From a clean clone, <code>./start.sh</code> does the same thing before it
      opens the editor, and skips straight to opening it every time after.</p>
      <h3>Getting GROMACS</h3>
      <p>If this machine has no <code>cmake</code>, first-run setup puts one in its own
      conda environment — no password needed — and the build script finds it there and
      puts that one directory on its PATH. It does not activate the environment, which
      would bring its libraries along. A missing <i>compiler</i> is different: a conda
      toolchain builds a GROMACS that needs that environment present to run, so for
      that one the answer is your package manager.</p>
      <p>Two ways, and neither is a conda environment. Point <b>Settings</b> at a
      <code>GMXRC</code> you already have, or use <b>Build from source…</b>, which asks
      for the version and the flags — GPU backend, MPI, SIMD level — and registers what
      it produces.</p>
      <p>The conda package was removed on purpose. It is one build with the choices
      already made: no GPU, no MPI, SIMD for whatever machine built it. It also puts a
      second <code>gmx</code> on your PATH whenever that environment is active, which is
      a good way to run the wrong one for a week without noticing.</p>
      <h3>Building GROMACS yourself</h3>
      <p>The conda package is one build with one set of choices: no GPU, no MPI, and
      SIMD for whatever machine made it. Everything people actually complain about —
      why is it not using my card, why can I not run across nodes — is a build-time
      flag. <b>Environments → Build from source…</b> offers the version, the install
      prefix, the GPU backend, MPI, double precision and the SIMD level, shows the
      exact script before it runs, and registers the result when it finishes. An MPI
      build installs <code>gmx_mpi</code> and no <code>gmx</code> at all, so the binary
      name is registered alongside the GMXRC.</p>
      <p>It compiles for the better part of an hour and wants a few GB of disk. A
      system prefix needs sudo, which this will not ask for on your behalf — copy the
      script and run it yourself instead.</p>
      <p>If that prefix already holds a build, the button says <b>Already installed</b>
      and does nothing: point it somewhere else to keep both, or tick <i>build it again
      anyway</i> to replace it. While any install or build is running there is a
      <b>Stop</b> button beside it.</p>
      <h3>Environments</h3>
      <p>An environment is a separate folder with its own copy of Python and the
      packages one tool needs, so that installing one tool cannot break another.
      Tools that are always used together share one, rather than each paying for its
      own copy of Python.</p>
      <p><b>Environments → Conda environments</b> lists what is on disk, what each one
      holds, and gives each a <b>Delete</b>. Deleting asks first and says which tools
      resolve through it — they stop working until pointed somewhere else.</p>
      <h3>Two versions at once</h3>
      <p>Picking a version in an install dialog names the environment after it —
      <code>md_analysis-2.9.0</code> rather than <code>md_analysis</code> — so it lands beside
      what you already have instead of over the top of it. The Environments panel
      lists every environment that actually holds each tool, including ones you made
      yourself, and switching between them is one click.</p>
      <p>A single node can use a different one: open its advanced parameters and pick
      from <b>Use this installation</b>. That is how you run one grompp against 2024.4
      and the next against 2026.3 in the same graph. For GROMACS the list is builds
      rather than environments, so it takes a version like <code>2024.4</code> or a
      path to a GMXRC — and where you have two builds of the same version, one MPI and
      one double precision, it offers the paths so there is no guessing.</p>
      <h3>Keeping the software current</h3>
      <p><b>Environments → Check for updates</b> asks each index what it has and
      shows it against what is installed. It takes twenty-odd seconds because a
      conda search does; that is why it is a button rather than something the dialog
      does by itself. Every install dialog also has a <b>Version</b> list, so you can
      pin an exact one rather than taking the newest.</p>
      <p>Updating replaces what is in that environment. A workflow that ran against
      the old version may not run the same way against the new one — if that matters,
      install into a differently named environment and point the tool at it.</p>
      <h3>Before anything installs</h3>
      <p>Every install checks what it needs first and says so on the dialog rather
      than failing partway through a script: conda for anything that goes into an
      environment. A GROMACS build checks cmake, make and a compiler, and whether the
      GPU backend you picked has its toolkit here at all.</p>
      <p>What it shows is the ways out that would work on <i>your</i> machine: the
      package line for your distribution, conda or pip where the thing can be had
      without root, and where a copy is already sitting in an environment, that.</p>
      <h3>Graphics drivers</h3>
      <p>Comfy-gmx does not install them, and will not offer to. A driver is a kernel
      module, usually a reboot, and getting it wrong costs you the display on the
      machine you were working at — that is your distribution's job, not a molecular
      dynamics tool's.</p>
      <p>What it does is check. There are three separate things and they are easy to
      confuse: the <b>driver</b> makes the card work at all, the <b>runtime library</b>
      is what a finished GROMACS loads, and the <b>toolkit</b> is what building one
      needs. Only the last is a package this can hand you a line for. The build dialog
      says which of the three is missing, because a toolkit with no driver builds
      perfectly and then fails at your first run.</p>
    `;
    const toc = body.querySelector('nav');
    const search = UI.el('input', {
      type: 'search', class: 'help-search', placeholder: 'search the help…',
    });
    toc.appendChild(search);
    const headings = [...article.querySelectorAll('h2, h3')];
    headings.forEach((heading, index) => {
      heading.id = `help-${index}`;
      toc.appendChild(UI.el('a', {
        class: heading.tagName === 'H2' ? 'toc-group' : 'toc-item',
        href: `#help-${index}`, text: heading.textContent,
        onclick: (event) => {
          event.preventDefault();
          // Not scrollIntoView: the article is a scroller inside a modal that
          // is itself a scroller, and scrollIntoView picks one of them to move
          // -- usually the wrong one. Its own scrollTop is unambiguous.
          article.scrollTo({ top: heading.offsetTop - article.offsetTop });
        },
      }));
    });

    /* Filtering hides sections, not words: what you want is the paragraph the
       word is in, and the heading above it so you know where you have landed. */
    search.addEventListener('input', () => {
      const needle = search.value.trim().toLowerCase();
      let shown = 0;
      for (const heading of headings) {
        if (heading.tagName === 'H2') continue;
        const block = [heading];
        for (let node = heading.nextElementSibling;
          node && !['H2', 'H3'].includes(node.tagName); node = node.nextElementSibling) {
          block.push(node);
        }
        const hit = !needle
          || block.some((node) => node.textContent.toLowerCase().includes(needle));
        if (hit) shown += 1;
        for (const node of block) node.classList.toggle('hidden', !hit);
        const link = toc.querySelector(`a[href="#${heading.id}"]`);
        if (link) link.classList.toggle('hidden', !hit);
      }
      // A group heading with nothing left under it is a lie.
      for (const heading of headings) {
        if (heading.tagName !== 'H2') continue;
        let any = false;
        for (let node = heading.nextElementSibling;
          node && node.tagName !== 'H2'; node = node.nextElementSibling) {
          if (node.tagName === 'H3' && !node.classList.contains('hidden')) any = true;
        }
        heading.classList.toggle('hidden', !any);
        const link = toc.querySelector(`a[href="#${heading.id}"]`);
        if (link) link.classList.toggle('hidden', !any);
      }
      article.classList.toggle('nothing-found', Boolean(needle) && !shown);
    });
    search.addEventListener('keydown', (event) => event.stopPropagation());

    UI.modal('Help', body, [{ label: 'Close' }]);
  },
};
