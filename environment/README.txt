VALORANT RENDER LAB

Run from the workspace:
  powershell -ExecutionPolicy Bypass -File environment/launch.ps1

Save a 1920x1080 scene image and camera/material metadata:
  powershell -ExecutionPolicy Bypass -File environment/launch.ps1 -Capture -Character viper

Render comparison frames (highlight on/off, cover, and several characters):
  powershell -ExecutionPolicy Bypass -File environment/launch.ps1 -Verify

Check runtime loading for all 29 characters:
  powershell -ExecutionPolicy Bypass -File environment/launch.ps1 -VerifyAll

The character selector loads all 29 downloaded character-select models at runtime.
The center and far-right actors are enemies; the left actor is a teammate.
Use right-drag to orbit, the wheel to zoom, or WASD/QE to move the camera target.
The panel provides animation selection, pause, rotation, foreground cover, and
Fresnel controls. F12 captures the scene without the control panel.
Captures and JSON metadata are saved in environment/captures/.

RENDERING BASIS
Riot's engineering description calls this Friend-or-Foe Fresnel: colored lighting
at grazing angles, biased toward up-facing surfaces and the upper character.
The source describes red enemies and neutral blue allies. We implement that
documented behavior with an adjustable purple enemy tint. It is surface lighting,
not a screen-space border or a through-wall silhouette. Normal depth testing
keeps the light hidden by opaque cover.
https://www.riotgames.com/en/news/valorant-shaders-and-gameplay-clarity

PURPLE COLOR
The in-game option is Purple (Tritanopia), under General > Accessibility > Enemy
Highlight Color. We sampled an original gameplay screenshot credited to esports.gg:
https://esports.gg/news/valorant/how-to-change-enemy-color-in-valorant/
https://media.esports.gg/uploads/2023/07/Purple-Enemy-VALORANT-1024x576.jpg
The selected purple pixels have median sRGB (176,77,190), hex #B04DBE.
See references/color_measurement.json for the ROI and selection thresholds.
This is a JPEG screenshot estimate, NOT Riot's verified internal shader constant.
Lighting, antialiasing, tone mapping and the underlying material change final pixels.
Fresnel power, intensity and height/direction masks are our approximation, not
recovered game code or gradient textures. The color picker supports calibration.

LIMITATIONS
This is an original practice-range blockout, not an extracted Valorant map.
Character-select animations are not a full gameplay locomotion/weapon pose set.
PBR base/normal/ORM/emission textures are restored using the viewer configurations.
Special eye, glass, decal and other custom effects are approximated and may differ
from the original viewer/game. No synthetic training labels are generated yet.
The 70.53-degree vertical FOV corresponds approximately to 103 degrees horizontally
at 16:9; this is an explicit camera preset, not a claimed measurement of the game.
The interactive preview resizes with its panel; captures use fixed 1920x1080.
Do not treat screenshot color calibration or synthetic render performance as
validation against actual gameplay. A real-game validation set remains necessary.

ASSETS
Models and original textures: ../assets/source/kingdomarchives/
Original download URLs and hashes are retained in each character's manifest.
The portable Godot engine is in ../tools/godot/.
