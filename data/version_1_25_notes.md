# Pokemon typing version 1.25

## Pokédex search cross-browser fix

This patch updates the Pokémon Profile search dropdown to behave consistently across Chrome, Edge, Safari, and Firefox.

Changes:
- Suggestion items now select on pointer/mouse down before the dropdown can be dismissed.
- Enter and NumpadEnter select the highlighted suggestion.
- Arrow Up / Arrow Down move the highlighted suggestion.
- The top suggestion remains auto-highlighted.
- Added combobox/listbox ARIA attributes for more stable browser behavior.

No backend/data changes are required for this patch.
