# How the tutorial website is made

The pages at <https://cwoodkid.github.io/comfy-gmx-lite/> are made from this
folder by [MkDocs](https://www.mkdocs.org/), with the
[Material](https://squidfunk.github.io/mkdocs-material/) look. This file is
not one of the pages.

## What is where

| path | what it is |
| --- | --- |
| `index.md` | the home page |
| `basics.md` | "Before you start": the parts of the screen, and the few things done again and again |
| `ice/`, `lysozyme/` | one page for each tutorial, and one for each of its boxes |
| `pictures/` | the pictures, one folder for each tutorial and one for `basics.md` |
| `_generated/` | the lists of blocks, settings, wires and commands; written by a script, never by hand |
| `stylesheets/extra.css` | the coloured dots in the wire tables, and the frames around pictures |
| `../mkdocs.yml` | the menu, the look, and the settings of MkDocs |

## The words, and the facts

A page's own words are in its `.md` file. The facts about a box, which blocks
to add, which settings to change, which wires to draw and which commands run,
are not typed in by hand. `tools/website.py` writes them into `_generated/`
from the tutorials themselves, and a page pulls them in with a line such as

    --8<-- "_generated/lysozyme/box-3-build.md"

After any change to a tutorial, or to the settings of a block a tutorial
uses, run `python3 tools/website.py` in the top folder and commit what it
writes. The self-test, `tools/smoke_test.py`, fails while they are out of
date, and when a page names a picture that is not there.

The pages about Lysozyme in Water explain each step in words of their own.
The published tutorial's explanations are Justin A. Lemkul's and are not
copied here: each page links to the step it follows.

## The pictures

`tools/website_pictures.js` takes the pictures from a running editor, through
a Chrome without a window. Its first lines say how to start it. It takes
three kinds:

- **the boxes as built**, one picture per box with the order of its blocks
  numbered (`box-1.webp`, ...). Nothing runs, so any copy of the editor will
  do.
- **`results`**: it presses **Run**, waits for the whole tutorial, and takes
  each box again with its results (`box-1-results.webp`, ...), and every
  graph and movie block on its own. Take these on mybinder.org, where the
  run costs your own computer nothing.
- **`screen`**: the whole editor with its four parts numbered, for
  `basics.md`. Take it online too: the **Command** tab in it shows the run
  folder, which on your own computer is a path that names you.

The numbers on the blocks come from `_generated/<tutorial>/boxes.json`, so a
picture and its page always agree. The numbers the pages quote from a run,
such as the density at the end of NPT, come from the same run as the
pictures: when the pictures are taken again, check the numbers on the pages
against the new graphs.

## Looking at it before it is published

From the top folder:

    pip install mkdocs==1.6.1 mkdocs-material==9.7.7
    mkdocs serve

then open <http://127.0.0.1:8000>. The pages change as you save them.

## Publishing

`.github/workflows/website.yml` builds the pages and publishes them after
every push to `main` that changes `website/` or `mkdocs.yml`. It builds with
`--strict`, so a broken link or a missing picture stops it rather than
publishing a broken page. GitHub Pages has to be switched on once, in the
repository's **Settings**, **Pages**, with **Source** set to **GitHub
Actions**.
