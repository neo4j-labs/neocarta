# Design decisions

This document records design trade-offs the pipeline deliberately makes,
in plain terms. It is the place to look when a behavior seems surprising
and you want to know whether it was a choice and why.

## Key-like columns

### What they are

A "key-like" column is a column that something else is allowed to point
at. A foreign key is a pointer: one column in one table points at a
column in another table. For example, an `owner_ref` column in an orders
table points at the `id` column in a users table. The column being
pointed at is the target. A key-like column is a column that can validly
serve as one of those targets, because it uniquely identifies a row.

### How they are decided

A column is treated as key-like when any of the following is true:

1. It is declared as a single-column primary key.
2. It is the leading column of a declared unique constraint.
3. Its name is exactly `id`.
4. Its name is the table name followed by `_id`, and it is the only
   column in that table whose name ends in `_id`.

The first two rules trust what the schema declares. The last two are
name-based fallbacks for the very common case where a table has a clear
logical key but nobody declared a constraint for it.

### Why they are needed

The pipeline finds hidden foreign keys by meaning, not just by name. It
asks "which column means roughly the same thing as this one?" and uses
the closest answers as candidate targets.

The danger is that a plain similarity search returns many columns that
could never be valid targets, such as free-text notes or description
fields. Those get discarded afterward. If the closest results are all
discardable, the one real target that was slightly further away never
gets considered, and a valid foreign key is silently lost with no error.

Marking the valid targets up front fixes this. The similarity search is
pointed only at key-like columns, so it can only return real candidates.
Nothing good gets crowded out by junk.

### How they are used

Key-like columns are identified once, early in a run. The columns that
qualify are tagged so they can be found quickly later. A dedicated
similarity search is built over only those tagged columns. When the
pipeline later guesses hidden foreign keys, it searches that narrow set
instead of every column in the catalog. The broad search used by the
client-facing chat and retrieval features is left exactly as it was, so
this change does not affect them.

## Trade-off: key-like targets restrict only inferred foreign keys

### The decision

Only inferred foreign keys are restricted to key-like targets. Inferred
means the pipeline guessed the link from column names or from meaning.
Foreign keys that the catalog actually declares are read straight from
the catalog and are never filtered by the key-like rule.

### Why this is safe for declared foreign keys

A declared foreign key is required by the catalog to point at a primary
key or a unique column on the parent table. A valid declared foreign key
target is therefore always key-like by definition. There is no such
thing as a valid declared foreign key that points at a non-key column,
so this filter can never drop one.

### Where a valid foreign key can still be missed

The exposure is entirely on the guessing path, and only for tables that
declare no primary key or unique constraint and whose key is not named
`id` or `<table>_id`. Examples of targets that would be missed:

- Natural or business keys such as `email`, `sku`, `isbn`,
  `account_number`, or a country code.
- Keys named differently from their table, such as `cust_no` in a
  customers table or a `user_uuid`.
- Tables with several `_id`-style columns, where the name-based fallback
  deliberately backs off to avoid guessing wrong.

For an inferred foreign key pointing into one of those targets, the link
is missed, because nothing marks the target as key-like and it is not
included in the narrow similarity search.

### Why we accept this

A foreign key that points at a non-unique, undeclared column is not a
sound relational reference in the first place, so requiring key-like
targets matches correct database design. The name-based fallbacks
already cover the dominant lakehouse convention, where keys are called
`id` or `<table>_id`. The clean fix for any remaining important case is
to declare the primary key in the catalog, even as an informational
constraint that is not enforced, which closes the gap completely.

How often this actually bites is a property of a specific catalog, not a
general fact, and is best measured against the real catalog rather than
assumed. We accept the residual gap rather than widening the name-based
guessing, because looser guessing trades a small recall gain for a
larger risk of inventing foreign keys that do not exist.

## How foreign keys are found

### The three ways, in order

The pipeline tries to find foreign keys (the pointers from one table to
another) in three ways, from most certain to least certain:

1. **Declared.** The catalog itself states the foreign key. This is read
   straight off the catalog. It is exact and is always trusted.
2. **By name.** No declaration exists, but the names give it away, such as
   a `customer_id` column lining up with the `id` column of a customers
   table. This is a strong, cheap signal.
3. **By meaning.** Neither of the above applies, so the pipeline compares
   what the columns *mean* and links the closest match, such as an
   `owner_ref` column that clearly refers to users even though its name
   never says "user". This catches links the names hide.

### Why the order matters

Earlier ways are more trustworthy, so they win. A link the catalog
declares is never second-guessed by a name or meaning guess, and a clear
name match is preferred over a meaning guess. The later ways only fill in
what the earlier ones did not already find. This keeps confident facts
confident and uses guessing only where there is nothing better.

## The "both sides are just called id" problem

> **Status: the value-overlap rescue described in this section was dropped
> and is no longer part of the pipeline.** A pair where both sides are just
> named `id` is now simply held back, permanently, with no rescue. The
> "shared example values" rescue below was judged not worth its cost: the
> set of cases where it actually helps in a large enterprise catalog is too
> narrow to justify the sampling, the id-vs-id comparison, and the overlap
> join it required. The current behavior is the "The problem" subsection
> only; everything from "The rescue" onward is retained **for historical
> reference**, to explain what was tried and why it was removed. The sound
> fix for a both-`id` link that genuinely matters is to declare the foreign
> key (or primary key) in the catalog, even as an informational, unenforced
> constraint, which moves it onto the exact, always-trusted declared path.
> Note this is only about the *rescue*: sampled Value nodes themselves are
> still produced and are still used elsewhere (client text-to-SQL grounding).

### The problem

Many tables have a key column simply called `id`. If the pipeline guessed
links purely from names, every `id` would look like it could point at
every other `id`, which would invent a flood of foreign keys that do not
exist. To avoid that, a pair where both sides are just named `id` is held
back by default rather than asserted.

### The rescue: shared example values

Holding those pairs back would also lose the real links among them. So
there is a rescue: the pipeline samples a handful of actual values from
each column and checks whether they genuinely overlap. If one column's
sampled values really do appear in the other, that is concrete evidence of
a real relationship, not just a coincidence of naming, and the link is
allowed back in.

### Why the rescue only works for small lists

This rescue is reliable only for columns with a small number of distinct
values, such as a status, type, or category key. For those, the sample
captures almost every value, so a true overlap is actually seen.

For a high-volume identifier with millions of distinct values, sampling a
few from each side will almost never land on the same ones, even when one
column genuinely references the other. The overlap evidence simply will
not appear by chance. Because of this, very high-variety columns are
deliberately left out of value sampling entirely. The rescue is, by
design, a small-list tool only.

### The accepted miss

This leaves one specific gap. A high-volume surrogate key (think a long
numeric or UUID id with millions of distinct values) that also has no
declared foreign key, no helpful name, and no clear meaning signal will
not be linked. The declared, name, and meaning ways all came up empty, and
the value rescue cannot apply because the column is too high-variety to
sample usefully.

We accept this. Collecting more samples does not fix it, because the odds
of overlap stay vanishingly small for high-variety columns. The sound fix
for any case that genuinely matters is to declare the foreign key (or the
primary key) in the catalog, even as an informational, unenforced
constraint, which moves the link onto the exact, always-trusted path. We
prefer that to loosening the guessing, which would trade a little extra
recall for a much larger risk of inventing relationships that are not
real.

## Tagging key targets with a second write

### What it is

Key-like columns need an extra tag that marks them as valid foreign-key
targets. That tag is added by writing those columns to the graph a second
time, instead of tagging them during the one main write of all columns.

### How it works

When columns are saved to the graph, the save applies the same tag to
every column in that batch. It cannot say "this column gets one tag and
that column gets two" in a single save. The tag is a property of the
whole write, not of each row.

So all columns are first saved with the ordinary column tag. Then the
small set of key-like columns is saved a second time with the extra
key-target tag added. Both saves find a column by the same identity, so
the second save does not create anything new. It only adds the extra tag
to the column that is already there. Running it again changes nothing,
which keeps re-runs safe.

The repeated work is only the cheap "find this column and add a tag"
step, and only for the key-like columns, which are a small fraction of
all columns. The expensive part, turning each column into its meaning
vector, still happens exactly once. It is not repeated.

### Why it is important

The reason this is worth calling out is that it looks wasteful at first
glance, and someone is likely to ask why it is not a single pass. It is a
deliberate choice. The graph connector already has a safe, well-tested way
to save and re-save by identity, and re-running it never duplicates or
corrupts anything. Doing the tagging as a second save of a small subset
stays entirely on that trusted path. The alternative, hand-writing a
custom save that conditionally adds the tag in one pass, would be faster
but would replace the trusted save with our own, which is more to get
right and more to maintain.

### The optimization we deferred

There is a clean middle option that removes the repeated save while still
using the trusted path: split the columns into two groups up front, the
key-like ones and the rest, and save each group exactly once with its own
tag. No column would be saved twice.

We did not do this yet because the current waste is small. Key-like
columns are a minority, the repeat is only the cheap tagging step, and the
costly vector step already runs once. This is a polish optimization, not a
correctness or speed problem. If the second save ever shows up as a real
cost on a large catalog, splitting into two groups is the preferred way to
remove it.

## Future extension: widening recall if matching proves insufficient

### Why this is open

This is an open-source project. At the time of writing we have only a few
sample catalogs and no real picture of what community catalogs will look
like once it is released. Rather than guess and over-build, the pipeline
ships with the conservative, predictable behavior described above, and
this section records what to change first if the community finds it is
not matching enough foreign keys in practice.

### The one bottleneck to look at first

If foreign keys are being missed, the cause is almost certainly key-like
target detection, not name matching. Both guessing layers, by name and by
meaning, can only ever point at a column the pipeline considers a valid
key target. A column counts as a valid target only when the catalog
declares it a primary key or unique, or its name is exactly `id` or the
table name followed by `_id`. On catalogs that declare their keys this is
fine. On raw catalogs that declare nothing and use business names for
keys, such as `email`, `sku`, or a country code, those targets are
invisible to both guessing layers at once. That single rule is the
ceiling on how many foreign keys can ever be found by guessing.

The name matcher itself is deliberately simple and should be left that
way. It is meant to be high-precision and low-recall: catch the obvious
cases cheaply and never invent links. Its known misses, such as
`company_id` not reaching a `companies` table because the plural rule is
mechanical, are the job of the meaning-based layer, not a reason to make
name matching fuzzier. Loosening it would trade a little recall for many
false links in the layer least able to afford them.

### Measure before changing anything

The first step is not a code change. It is a read-only measurement
against a real catalog: how many target tables actually declare a primary
key or unique constraint versus none, and how many candidate links are
lost only because the target is not considered key-like. This turns "it
might be missing things" into a number and shows whether any change is
worth making for that catalog.

### The principled widening, if the number is material

If the measurement shows real loss, the sound change is to widen what
counts as a valid key target using the data itself, not more name rules.
A column that is effectively unique across its rows (its number of
distinct values is at or near the row count, over a sensible minimum
table size) behaves like a key whether or not anyone declared it one.
Uniqueness is what "key-like" actually means, and the pipeline already
samples values, so the signal is close at hand. This raises recall
without inventing naming conventions and without loosening the guessing.
The cost is a cheap extra count and a guard so that tiny or empty tables
do not look falsely unique.

### What not to do

- Do not make name matching fuzzier. It is the precision layer; recall is
  the meaning layer's job.
- Do not rebuild the removed shared-example-values rescue for columns
  named `id`. It was dropped on purpose; its useful window is too narrow
  to justify its cost.
- Do not add generic identifier names to the "refuse when both sides
  match" rule as a way to gain recall. That rule is a precision guard,
  the wrong lever for recall.

### The always-available sound fix

Independent of any of the above, the exact and always-trusted way to make
any specific missed link appear is to declare the foreign key, or the
primary key it points at, in the catalog, even as an informational,
unenforced constraint. That moves the link onto the declared path, which
is never guessed and never filtered. Surfacing this guidance to anyone
running the pipeline on a new catalog is itself a low-effort,
high-leverage improvement.
