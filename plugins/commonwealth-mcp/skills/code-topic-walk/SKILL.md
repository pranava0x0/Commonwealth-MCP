---
name: code-topic-walk
description: >
  Reach a section of the Code of Virginia by topic when the reader has no
  citation, by walking the Code's own table of contents to it and then
  reading the section. Use when someone asks what state law says about
  zoning, annexation, FOIA, or any other subject without naming a section
  number. No public endpoint searches the Code's text, so a subject
  reaches a citation by walking the structure or not at all; where the
  walk does not reach one, the answer says so and names no section.
license: Apache-2.0
compatibility: >
  Requires Commonwealth-MCP v0.x under a profile carrying the civic
  toolset, which walking the contents needs; the `discovery` profile and
  above have it.
metadata:
  commonwealth:
    required_capabilities:
      - code_structure.browse
      - code_section.lookup
    example_prompt: >
      What does Virginia law say about a locality's authority to adopt a
      zoning ordinance? Walk me to the section.
---

# Code of Virginia, by topic

The publisher runs no full-text search operation. Its own search backend
was down when this was checked, and its JSON API has no search at all. So
a reader who says "what does Virginia law say about short-term rentals"
cannot be answered by searching, and the two ways to fail here are equally
bad: guessing a citation that sounds right, or answering the legal
question from memory and dressing it in a section number afterwards.

What is available is the Code's own structure: titles, a title's chapters,
a chapter's sections. That is a hierarchy a reader can be walked down, and
each level's rows carry the arguments for the level below. This walk is
that descent, and it states where the descent stopped.

## 1. Establish the frame

- **A title is a subject area, and the mapping from a question to a title
  is the hard step.** Local government is Title 15.2. Motor vehicles is
  46.2. Crimes is 18.2. That mapping is knowledge about the Code's
  organisation, not about the law, and it is the one place this walk
  reasons rather than reads.
- **A citation is `title-section`**, and the section number carries the
  chapter: 15.2-2200 is in Title 15.2, chapter 22. Reading that structure
  off a citation is how a caller who has one skips straight to the text.
- **Sections are repealed, renumbered, and added.** A citation that is not
  found is a fact about the Code as published today, not an error, and the
  publisher redirects rather than returning a not-found status.
- **The published text is the text.** It is not the annotations, the case
  law, or the regulations promulgated under it, and none of those are here.

## 2. Minimum data walk

**Step 1 — name candidate titles.** From the subject, propose the titles
that plausibly hold it, and say why each. Two or three, not one: a subject
often sits in more than one, and land use touches both local-government
authority and the enabling statutes for specific tools.

**Step 2 — read the title list and check the names.** Walk the contents
from the top and read the titles as published. This is the step that
catches a title that was renumbered or one that never existed under the
name assumed. A title the Code does not have and a title with no chapters
come back the same way, so say which question was asked.

**Step 3 — descend one level at a time.** A title's chapters, then the
chapter's sections. Read the headings as published; they are the only
subject index the source offers. Do not skip a level by guessing a
chapter number.

**Step 4 — read the section.** Take the citation the walk arrived at and
read the text, with the section's own citation history. Where the walk
produced several plausible sections, read them and say which answers the
question and which are adjacent.

**Step 5 — stop, or hand off.** If no chapter heading matches the subject
after a full descent, say the walk did not reach it, and say where a
reader should look instead. That is the answer, not a failure to produce
one.

## 3. Escalation table

| Finding | Next | Why |
|---|---|---|
| The subject could be in two titles | Walk both, report both | Choosing one silently hides a whole body of law from the reader |
| A chapter heading nearly matches | Read the section list before deciding | A heading is a label, and the operative section is often two headings away |
| The section arrived at cross-references another | Read the referenced section too | A section that defines its terms elsewhere cannot be read alone |
| The citation is not found | Report it as not found, with the citation asked for | A repealed or renumbered section is a real answer; an error is not |
| The walk reaches no matching chapter | Say the topic was not reached | That is where a source with no search ends; padding it with recalled law is the failure this walk exists to prevent |
| The reader is asking what the law requires of them | Say this is the text, not advice | Reading a statute and applying it are different acts |

## 4. Output contract

1. **The citation, in full**, and the title and chapter it sits under, so
   the reader can see how the walk got there.
2. **The published text**, quoted, and its citation history as published.
3. **The path walked** — which titles were considered, which chapters were
   read — because that is what makes the result checkable by someone who
   disagrees with the title choice.
4. **A link to the publisher's live page** for the section. The published
   site is authoritative and this is a copy of what it said when fetched.
5. **What was not established.** Regulations, case law, local ordinances,
   and later amendments are all outside what was read.

## 5. Stop conditions

Done when the section is read and its path is shown, or when the walk
reports that it did not reach the subject.

Refuse, and say why:

- **Legal advice, or whether a statute applies to a situation.** The text
  is what this returns. Applying it is a lawyer's act, and a wrong answer
  here has consequences a citation cannot undo.
- **Any claim that a search was run.** There is no search endpoint. A
  sentence implying the Code was searched for a phrase is false about the
  method, whatever the citation turns out to be.
- **Local ordinances.** A locality's own code is not the Code of Virginia.
  Where a question is really about a locality's ordinance, say so; state
  law is where the locality's authority to adopt it comes from, and the
  two answer different questions. [[zoning-with-enabling-statute]] is the
  walk that keeps those two claims apart.
- **Inferring a section number from a subject.** If the walk did not reach
  it, it was not reached.
