# Pokemon typing version 1.26

## Pokédex search cross-browser follow-up

This patch hardens the Pokédex profile search dropdown for Chromium/Safari-based browsers.

Changes:

- Suggestion selection is handled at document capture phase before blur/outside-click logic can hide the dropdown.
- Dropdown options are non-focusable but pointer/touch selectable.
- Mouse, pointer, touch, and click events all route through one selection handler.
- Keyboard navigation still works even if focus briefly leaves the text input while the dropdown is open.
- Selecting a suggestion refocuses the input and immediately loads the profile.

Only `templates/pokemonprofile.html` changed from version 1.25, plus this notes file.
