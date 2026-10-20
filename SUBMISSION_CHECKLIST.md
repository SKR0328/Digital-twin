# Submission checklist

This checklist follows the mandatory items shown in the competition submission
form supplied by the participant. Checked items are present in this local
package; they do not imply that the package has already been published.

- [x] Team details: Surajkumar Reddiar; individual entry with one member.
- [x] College information: Rajiv Gandhi Institute of Technology.
- [x] Project title: GlycoAhead.
- [x] Problem statement in the README.
- [x] Healthcare use case in the README.
- [x] Technical stack in the README.
- [x] AI/ML framework and model details in the README and model card.
- [ ] A 15–20 minute video uploaded as **Unlisted** on YouTube, with a working link in the README.
- [x] Open-source code license: MIT; separate data/reference attribution retained.
- [x] [Architecture diagram in PDF format](submission/GlycoAhead-Architecture.pdf).
- [x] [Presentation in PDF format](submission/GlycoAhead-Presentation.pdf), including project outcomes.
- [ ] Public GitHub repository and all required files/links accessible without additional permission.

## Remaining actions

1. Add the final YouTube URL to the README's **Submission files and video**
   section. Confirm that the finished video lasts 15–20 minutes and its visibility
   is **Unlisted**, not Private.
2. Publish the prepared folder as the root of a public GitHub repository.
3. Open the repository while signed out, or in a private browser window.
4. Follow both PDF links from the GitHub README. Confirm that the PDFs open or
   download without requesting access.
5. Follow the video link while signed out. Confirm that it plays without asking
   for permission and that the upload has finished processing.
6. Only then mark the remaining boxes complete and paste the public repository
   URL into the competition form.

## File locations

- Architecture: `docs/submission/GlycoAhead-Architecture.pdf`.
- Presentation: `docs/submission/GlycoAhead-Presentation.pdf`.
- Team/link metadata: `docs/submission.json`.
- Model evidence: `release/selected_model/comparison.json` in the upload package.

## Rebuilding the PDFs

The application does not need PDF-authoring libraries to run. To regenerate the
submission documents, install `reportlab` in a document-authoring environment and
run `python scripts/build_submission_pdfs.py` from the project root. Outputs are
written to `output/pdf/` and copied into `docs/submission/` for repository links.
Re-render and inspect the PDFs after any layout or content change.
