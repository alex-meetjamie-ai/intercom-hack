# Office Hours — Linienstraße 144

A six-scene Three.js story about a DHL parcel delivery to our Berlin rooftop office. The sunny cream, coral and sage world fills the screen, with minimal dark controls. Geometry is generated locally, using the supplied street and office photos as references. The photos themselves are not bundled or uploaded.

## Run

Requires Node.js 22.12+ or a supported newer LTS release.

```sh
cd ~/Developer/intercom-hack/threejs
npm install
npm run dev
```

Open the local URL printed by Vite. The presentation starts close to the street intercom. Click its **Jamie** button to start the microphone call through the shared client. The intercom indicates Calling / Listening; click it again to hang up. Backend entry approval moves the camera through the building automatically. Click the physical elevator button to call the lift and continue upstairs. Egor’s phone remains directly clickable. There are no slide numbers or Next buttons. Keyboard users can Tab to equivalent controls; Escape ends an active call.


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
- `src/characters.js`: courier, parcel, Egor, phones and walking/waving poses.
- `src/main.js`: rendering, navigation, notification decision controls and optional backend events.
- `src/style.css`: the minimal dark overlay controls around the full-screen daylight scene.

## Camera and model presentation

The street entrance, courtyard, rear building, elevator and loft remain in the same world throughout the tour. The corrected overhead layout follows the annotated map: the office spans the rear of the courtyard, parallel to the street. The elevator sits in the junction of the rear and left courtyard walls, with a right-facing ground-floor entrance. The office and terrace are offset left of the fixed shaft, placing the lift at the terrace’s right end; the upper door opens left onto the deck. The compact elevator/terrace annex projects from its courtyard-facing long edge on the approaching courier’s left (the right of the map with the street at the top). The roof and desk layout retain their 90-degree orientation inside the office footprint. Office, rear facade, entrance and terrace share the leftward offset; the lift and courtyard approach retain their positions. Roof geometry is fitted to the rectangular slab, while furniture keeps its proportions. The new exterior references inform the yellow-brick rear facade, slate beds, dark central path, an open rear passage to the next courtyard, attached front deck, white parapet and metal-framed entrance. The foreground facade and right wing gradually become translucent cutaways where they would obscure the route. There are no scene fades, hidden swaps or character teleports between normal stops.

A single playhead drives the camera, courier, doors, lift and Egor. The camera flies over the courtyard for Egor's notification and back to the entrance; it then follows the courier through the passage, around the courtyard and vertically with the lift. At the top, it turns toward the office while the courier leaves the left-facing upper lift portal and crosses the attached deck to the office. Free orbit is available at each stop; the camera eases back into the route on the next action.

For development-only still-frame review, open `/?reviewTo=3&reviewAction=0.5` for the courtyard walk or `/?reviewTo=4&reviewAction=0.52` for the lift ride. `/?reviewFrom=0&reviewTo=5&reviewAt=0.5` samples halfway through the shared timeline between those stops. These options are disabled in production builds. Add `&plan=1` to a review URL for a top-down layout check with the street at the top. Remove the query string for the normal tour.

## Shared backend client

Alex's implementation in `../client` owns SIP, WebRTC audio and backend status. `src/intercom-client.js` is a Three.js presentation adapter: it subscribes to the existing `/employee` WebSocket, displays the current approval on the phone and sends Yes/No decisions. It does not change the agent's prompt, speech, entry policy or tools.

Run the backend on port 8740, then `npm run dev` here. Vite proxies `/api`, `/sip`, and `/employee`; `BACKEND_URL` overrides the target. The bottom-left links open Alex's original Intercom, How it works and Admin pages on the backend.

The rear passage is structural geometry: side piers and an overhead brick section leave the aperture open through the block. Its floor continues to a small rear landing. The obsolete decorative doorway beside the lift has been removed.

## Immersive presentation

The 3D canvas fills the screen. A small dark transport control provides Back, Next and replay; Space or the arrow keys also advance. Yes/No are clickable on Egor’s physical phone screen; keyboard users can Tab to equivalent controls. Choosing an answer animates his fingertip tapping it before the story continues. Architectural signs remain, while floating character labels and landing-page copy are hidden. Daylight lighting stays warm and bright. The camera closes in for the intercom press, travels to Egor and his phone, then focuses on the call pedestal and the right-hand elevator entrance. The courier makes physical fingertip contact with both buttons; the lift starts descending after the call. The camera opens out during ascent.

## Live presentation sequence

Click Jamie and speak while the camera stays at the intercom. A pending employee approval from the backend moves the camera to Egor; the presentation waits for a manual Yes or No while the backend request remains pending. Yes starts the courtyard walk, simulated agent lift dispatch, boarding and ascent automatically. Arrival ends in a close rooftop greeting with confetti. No sends a denial and returns to the intercom; Alex’s backend handles the refusal and hangup.

The existing backend grants and unlocks automatically; the manual gate is in the presentation. Lift dispatch is a scene animation because this backend has no elevator endpoint. Backend code is unchanged.
