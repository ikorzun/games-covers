# Game Covers (GitHub Pages template)

Static hosting for game cover images + auto-generated `covers.json` via GitHub Actions.

## Quick Start

1. Create a **public repo** on GitHub, e.g. `game-covers`.
2. Upload all files from this template to the repo.
3. Go to **Settings → Pages** and set:
   - **Source**: Deploy from a branch
   - **Branch**: `main` (root)
4. Open: `https://<username>.github.io/<repo>/covers.json` (replace with your username & repo).

## Add covers

Put images in `/covers` (png/jpg/webp). On push, the Action updates `covers.json` with full URLs.

## Use in Framer

```jsx
React.useEffect(() => {
  fetch("https://<username>.github.io/<repo>/covers.json?ts=" + Date.now())
    .then(r => r.json())
    .then(d => setCovers(d.covers))
}, [])
```
*Add a timestamp to bust the cache.*

## Custom domain (optional)
- Add a CNAME DNS record: `covers.yourdomain.com → <username>.github.io`
- In repo Settings → Pages, set **Custom domain** to `covers.yourdomain.com`

## Notes
- Avoid spaces in filenames. Use `kebab-case`.
- Prefer `webp` for smaller size.
- You can edit the workflow to change which folders it scans.