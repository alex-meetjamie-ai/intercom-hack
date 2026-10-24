# Office Hours — Linienstraße 144

A six-scene Three.js story about a pizza delivery to our Berlin rooftop office. The sunny cream, coral and sage world fills the screen, with minimal dark controls. Geometry is generated locally, using the supplied street and office photos as references. The photos themselves are not bundled or uploaded.

## Run

Requires Node.js 22.12+ or a supported newer LTS release.

```sh
cd ~/Developer/intercom-hack/threejs
npm install
npm run dev
```

Open the local URL printed by Vite. Use Next to advance. The camera and characters move together along one continuous timeline. Each button press plays the next part of the journey; the courtyard walk and lift ride each take eleven seconds. Drag to orbit once the animation finishes. Back retraces the current action. Restart travel through the same timeline at a faster pace when crossing several stops. Left/right arrow keys navigate when focus is outside a button. Reduced-motion preferences skip the animated movement and show each scene's final state.

```sh
npm run build
npm run preview
```

## The six scenes

1. The courier rings the intercom at the arched street entrance.
2. The camera travels to the loft; Egor receives a simulated push notification. **No** on his phone keeps the entrance closed. **Yes** advances the story after a tap animation.
3. The camera returns to the street and the entrance doors open.
4. The courier walks through the courtyard, turns left along the rear wall, and approaches the corner elevator from its right-hand side.
5. The courier boards; doors close before the glass elevator rises. The camera follows the cabin upward, then widens to reveal the rooftop landing.
6. The courier exits onto the compact attached terrace and walks across it to the courtyard-facing office entrance.

The surrounding floors and dimensions are intentionally schematic. `TOP` is a drawing coordinate, not a surveyed floor height or storey count. The visual references inform the cream facade, brown arched entrance, trees, charcoal external lift, wooden terrace, curved timber ceiling, angled glazing, pale desks and dark phone booths. Scaffolding is omitted. The cartoon people are illustrative characters, not photo-derived likenesses.

## Change the story or model

- `src/journey.js`: the six stops, shared timeline, action timing, walking routes and deterministic scene state. `sampleJourney(stop, progress)` supports replaying any stop without depending on previous animations.
- `src/camera.js`: continuous camera choreography, courier tracking, lift tracking and framing for free orbit.
- `src/layout.js`: the fixed plan footprint, separate roof/interior orientation, shared coordinates, courtyard-facing entrance and compact terrace bounds.
- `src/world.js`: street, courtyard, lift, loft, terrace, moving doors and scene updates.
- `src/geometry.js`: shared materials, geometric helpers, plants, labels and cutaway fading.
- `src/characters.js`: courier, pizza boxes, Egor, phones and walking/waving poses.
- `src/main.js`: rendering, navigation, notification decision controls and optional backend events.
- `src/style.css`: the minimal dark overlay controls around the full-screen daylight scene.

## Camera and model presentation

The street entrance, courtyard, rear building, elevator and loft remain in the same world throughout the tour. The corrected overhead layout follows the annotated map: the office spans the rear of the courtyard, parallel to the street. The elevator sits in the junction of the rear and left courtyard walls, with a right-facing ground-floor entrance. The office and terrace are offset left of the fixed shaft, placing the lift at the terrace’s right end; the upper door opens left onto the deck. The compact elevator/terrace annex projects from its courtyard-facing long edge on the approaching courier’s left (the right of the map with the street at the top). The roof and desk layout retain their 90-degree orientation inside the office footprint. Office, rear facade, entrance and terrace share the leftward offset; the lift and courtyard approach retain their positions. Roof geometry is fitted to the rectangular slab, while furniture keeps its proportions. The new exterior references inform the yellow-brick rear facade, slate beds, dark central path, an open rear passage to the next courtyard, attached front deck, white parapet and metal-framed entrance. The foreground facade and right wing gradually become translucent cutaways where they would obscure the route. There are no scene fades, hidden swaps or character teleports between normal stops.

A single playhead drives the camera, courier, doors, lift and Egor. The camera flies over the courtyard for Egor's notification and back to the entrance; it then follows the courier through the passage, around the courtyard and vertically with the lift. At the top, it turns toward the office while the courier leaves the left-facing upper lift portal and crosses the attached deck to the office. Free orbit is available at each stop; the camera eases back into the route on the next action.

For development-only still-frame review, open `/?reviewTo=3&reviewAction=0.5` for the courtyard walk or `/?reviewTo=4&reviewAction=0.52` for the lift ride. `/?reviewFrom=0&reviewTo=5&reviewAt=0.5` samples halfway through the shared timeline between those stops. These options are disabled in production builds. Add `&plan=1` to a review URL for a top-down layout check with the street at the top. Remove the query string for the normal tour.

## Shared backend client

All backend communication lives in `../client`, imported as `@intercom/client`. Three.js only supplies scene callbacks and an audio element.

Run the existing backend on port 8740, then `npm run dev` in this folder. Vite proxies `/api` and `/sip`; `BACKEND_URL` overrides the local target. Press **Speak to Jamie** to start a real microphone/WebRTC conversation. Live transcript text appears over the scene, and the backend opening the door advances the journey. **End call** or **No** ends the SIP call. **Yes** only continues after the backend grants entry; the current backend has no manual Yes endpoint.

The local backend needs its ElevenLabs agent configuration before voice can work. This integration does not change backend code, provision an agent, or expose its credentials. See `../client/README.md` for the client API. The door remains the backend's simulated door.

The rear passage is structural geometry: side piers and an overhead brick section leave the aperture open through the block. Its floor continues to a small rear landing. The obsolete decorative doorway beside the lift has been removed.

## Immersive presentation

The 3D canvas fills the screen. A small dark transport control provides Back, Next and replay; Space or the arrow keys also advance. Yes/No are clickable on Egor’s physical phone screen; keyboard users can Tab to equivalent controls. Choosing an answer animates his fingertip tapping it before the story continues. Architectural signs remain, while floating character labels and landing-page copy are hidden. Daylight lighting stays warm and bright. The camera closes in for the intercom press, travels to Egor and his phone, then focuses on the call pedestal and the right-hand elevator entrance. The courier makes physical fingertip contact with both buttons; the lift starts descending after the call. The camera opens out during ascent.
