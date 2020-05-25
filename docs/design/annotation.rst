Annotation related design notes
===============================


Point columns and rows start from 0, not 1
------------------------------------------
See issue #314. Up until early 2020, point column values ranged from 1 to the image width in pixels, and point rows ranged from 1 to the image height. This decision was either made arbitrarily, or made with a concern of being more intuitive to less-technical users.

However, there were some bounds checks, calculations, etc. across the site which mistakenly assumed the ranges were 0 to width-1 and 0 to height-1, or passed the point locations into 0-indexed coordinate systems (Pillow images, Javascript positioning, etc.) without first converting to 0-indexing. From this, and the fact that spacer was already assuming 0-indexing instead of 1-indexing, we realized it would make life easier to change everything in CoralNet to assume 0-indexing.


Points with the same row/column positions in the same image are allowed
-----------------------------------------------------------------------
See issue #308 - these 'duplicate points' are allowed because:

- By the time we seriously thought of disallowing them in 2020, we already had quite a few duplicate points in CoralNet - spanning 147 different sources. Any idea for removing/correcting these duplicates seemed risky and/or hacky.

- CPCe allows them.

- Allowing duplicate points is essentially doing sampling with replacement, which is a valid statistical method.

In the future, we may give users the option to disallow duplicate points or not when generating or uploading points. However, to our memory, no one has requested this yet. See issue #316.
