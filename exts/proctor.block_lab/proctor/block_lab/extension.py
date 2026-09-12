# ------------------------------------------------------------
# OMNIVERSE IMPORTS
#
# omni.ext Docs: https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/omni.ext.html
# omni.ui Docs: https://docs.omniverse.nvidia.com/kit/docs/omni.ui/latest/API.html
# omni.usd Docs: https://docs.omniverse.nvidia.com/kit/docs/omni.usd/latest/Overview.html
# omni.appwindow Docs: https://docs.omniverse.nvidia.com/kit/docs/omni.appwindow/latest/omni.appwindow.html
# omni.kit.app Docs: https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/omni.kit.app.html
# ------------------------------------------------------------

# Core Omniverse Kit extension API provides omni.ext.IExt for the extension lifecycle.
import omni.ext

# Omniverse UI toolkit (windows, labels, buttons, layouts, etc).
import omni.ui as ui

# Interface to the current USD context and Stage.
import omni.usd

# Access to Kit's application window (to retrieve the keyboard device for keyboard input).
import omni.appwindow

# Access to the running Kit application for Kit's update event stream / per-frame callback.
import omni.kit.app

# ------------------------------------------------------------
# PYTHON IMPORTS
#
# math Docs: https://docs.python.org/3/library/math.html 
# time Docs: https://docs.python.org/3/library/time.html
# ------------------------------------------------------------

# Python standard-library mathematics (for sin(), cos(), pi, degrees(), etc).
import math

# Python standard-library timing functions (time.monotonic() is used to measure projectile lifetime).
import time

# ------------------------------------------------------------
# OPENUSD / PHYSX IMPORTS
#
# OpenUSD Docs: https://openusd.org/release/api/usd_page_front.html
# PhysX Docs: https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.1/extensions/runtime/source/omni.physx/docs/api/python.html
# ------------------------------------------------------------

# OpenUSD geometry schemas (provides Cube, Sphere, Cylinder, Xform, Xformable, XformCommonAPI, etc).
from pxr import UsdGeom

# OpenUSD physics schemas (provides generic physics APIs such as CollisionAPI, RigidBodyAPI, and MassAPI).
from pxr import UsdPhysics

# NVIDIA PhysX-specific USD schemas (for PhysX properties beyond regular OpenUSD physics, such as solver position iteration count).
from pxr import PhysxSchema

# Core OpenUSD types (we are using Usd.TimeCode.Default() when calculating transforms).
from pxr import Usd

# OpenUSD graphics/math library (provides vectors and matrices such as Gf.Vec3d and Gf.Vec3f).
from pxr import Gf

# ------------------------------------------------------------
# CARBONITE IMPORTS
#
# carb.input Docs: https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/carb.input.html
# ------------------------------------------------------------

# NVIDIA Carbonite input API (for keyboard events and KeyboardInput / KeyboardEventType).
import carb.input

# ------------------------------------------------------------
# MIDO IMPORT VIA EXTENSION.TOML
#
# Docs: NVIDIA "Using Python pip Packages"
# https://docs.omniverse.nvidia.com/kit/docs/omni.kit.pipapi/110.1.1/Overview.html
#
# Docs: Mido Ports / Callbacks
# https://mido.readthedocs.io/en/latest/ports/
# ------------------------------------------------------------

# Mido is an external package for working with MIDI.
# Mido is installed into Kit's Python environment through [python.pipapi] in extension.toml.
try:
    import mido
    print("[proctor.block_lab] mido imported successfully")
    print("[proctor.block_lab] MIDI inputs:", mido.get_input_names())
except Exception as e:
    print("[proctor.block_lab] MIDI import failed:", e)


# MIDI controller Korg SQ-1 is producing note values from 48 through 108.
# (SQ-1 Mode: Active Step with 5V Range and Linear Behavior.)
# These become the input range for _map_midi_note().
# Note: Use aseqdump -p (midi port) to monitor MIDI messages
# for other MIDI controllers and calibrate for this app.
NOTE_MIN = 48
NOTE_MAX = 108


# ------------------------------------------------------------
# BLOCK LAB EXTENSION
# ------------------------------------------------------------

class BlockLabExtension(omni.ext.IExt):

    def on_startup(self, ext_id):
        # on_startup() is called when Kit enables the extension.
        #
        # Docs: NVIDIA Kit Extensions
        # https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/extensions.html

        print("[proctor.block_lab] Extension startup")


        # ------------------------------------------------------------
        # MIDI INPUT
        # ------------------------------------------------------------

        self._midi_port = None

        midi_inputs = mido.get_input_names()

        # Look for the USB MIDI interface connected to the SQ-1.
        for port_name in midi_inputs:
            if "USB Midi" in port_name:

                # Mido calls _on_midi_message() whenever a MIDI message arrives.
                #
                # The Mido callback runs on another thread. Because of that,
                # the callback should store data rather than directly modifying
                # the USD Stage.
                #
                # Docs: Mido callback threading
                # https://mido.readthedocs.io/en/latest/ports/

                self._midi_port = mido.open_input(
                    port_name,
                    callback=self._on_midi_message,
                )

                print(
                    "[proctor.block_lab] Opened MIDI input: "
                    f"{port_name}"
                )

                break


        # ------------------------------------------------------------
        # CANNON AIM STATE
        # ------------------------------------------------------------

        # Current angles actually being displayed by the cannon.
        self._azimuth = 0.0
        self._altitude = 0.0

        # Angles requested by the MIDI controller.
        #
        # The cannon gradually moves from the current angles toward these
        # target angles in _on_update().
        self._target_azimuth = 0.0
        self._target_altitude = 0.0

        # MIDI callback can use this flag to communicate with Kit's
        # main update loop without directly editing USD from the MIDI thread.
        # In other words, _midi_aim_dirty == True means the data have changed
        # and an update is needed during Kit's next update loop.
        self._midi_aim_dirty = False


        # ------------------------------------------------------------
        # USER INTERFACE
        # ------------------------------------------------------------

        # omni.ui is Kit's UI framework.
        #
        # Docs: NVIDIA omni.ui
        # https://docs.omniverse.nvidia.com/kit/docs/omni.ui/latest/omni.ui.html

        self._window = ui.Window(
            "Block Impact Lab",
            width=300,
            height=300,
        )


        # ------------------------------------------------------------
        # KEYBOARD INPUT
        # ------------------------------------------------------------

        # Get Kit's main application window.
        self._app_window = omni.appwindow.get_default_app_window()

        # Get the keyboard associated with that window.
        self._keyboard = self._app_window.get_keyboard()

        # Acquire Kit's input system.
        self._input = carb.input.acquire_input_interface()

        # Subscribe our callback to keyboard events.
        # Keep the returned subscription ID so we can unsubscribe later.
        #
        # Docs: NVIDIA Keyboard Input
        # https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/input-devices/keyboard.html

        self._keyboard_sub_id = self._input.subscribe_to_keyboard_events(
            self._keyboard,
            self._on_keyboard_event,
        )


        # ------------------------------------------------------------
        # PROJECTILE TRACKING
        # ------------------------------------------------------------

        # Dictionary containing projectile names and their creation times.
        #
        # Example:
        #
        # {
        #     "/World/Projectiles/Projectile_0001": 12345.67,
        #     "/World/Projectiles/Projectile_0002": 12346.20,
        # }
        #
        # _on_update() uses these timestamps to delete old projectiles.
        self._projectiles = {}

        # Every projectile gets a unique number and a unique USD path.
        self._projectile_counter = 0


        # ------------------------------------------------------------
        # KIT UPDATE LOOP
        # ------------------------------------------------------------

        # Subscribe to Kit's update event stream.
        #
        # _on_update() gets called once for every Kit update/frame.
        #
        # Used for:
        #
        #   1. Smooth cannon motion
        #   2. Moving MIDI state onto the USD Stage
        #   3. Deleting expired projectiles
        #
        # Keeping the subscription object alive keeps the callback active.
        #
        # Docs: NVIDIA Kit Event Streams / Update Events
        # https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/events.html
        
        self._update_subscription = (
            omni.kit.app.get_app()
            .get_update_event_stream()
            .create_subscription_to_pop(
                self._on_update,
                name="proctor.block_lab.projectile_cleanup",
            )
        )


        # ------------------------------------------------------------
        # BUTTON BOX WINDOW CONTENT
        # ------------------------------------------------------------

        with self._window.frame:
            with ui.VStack(spacing=10):
                ui.Label("Block Impact Lab")

                ui.Button(
                    "Create Tower",
                    clicked_fn=self._create_round_tower,
                )

                ui.Button(
                    "Create Cannon",
                    clicked_fn=self._create_cannon,
                )

                ui.Button(
                    "Create Ground",
                    clicked_fn=self._create_ground,
                )


    # ------------------------------------------------------------
    # KEYBOARD CONTROLS
    # ------------------------------------------------------------

    def _on_keyboard_event(self, event):
        # We currently respond only to the initial key press (key repeat is ignored).
        #
        # Docs: NVIDIA Keyboard Input
        # https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/input-devices/keyboard.html
        
        if event.type != carb.input.KeyboardEventType.KEY_PRESS:
            return True


        # Enter fires the cannon.
        if event.input == carb.input.KeyboardInput.ENTER:
            print("[proctor.block_lab] FIRE!")
            self._fire_cannon()


        # Arrow keys provide a simple non-MIDI aiming method.
        elif event.input == carb.input.KeyboardInput.LEFT:
            self._target_azimuth += 1.0

        elif event.input == carb.input.KeyboardInput.RIGHT:
            self._target_azimuth -= 1.0

        elif event.input == carb.input.KeyboardInput.DOWN:
            self._target_altitude += 1.0

        elif event.input == carb.input.KeyboardInput.UP:
            self._target_altitude -= 1.0

        return True


    # ------------------------------------------------------------
    # MIDI CONTROLS
    # ------------------------------------------------------------

    def _on_midi_message(self, message):
        # This function is called by Mido's MIDI callback thread.
        #
        # We do NOT directly edit the USD Stage here.
        # Instead, we update normal Python values and let _on_update()
        # handle the USD changes from Kit's update loop.
        #
        # Docs: Mido callbacks
        # https://mido.readthedocs.io/en/latest/ports/


        # We only care about "note_on" values. (Ignore MIDI clock, Active Sensing, note_off, etc.)
        if message.type != "note_on":
            return

        # MIDI sometimes represents note-off as note_on with velocity 0.
        if message.velocity == 0:
            return


        # SQ-1 MIDI Channel 0 controls altitude.
        #
        # Note range becomes 0-45 degrees.
        if message.channel == 0:
            self._target_altitude = self._map_midi_note(
                message.note,
                0.0,
                45.0,
            )


        # SQ-1 MIDI Channel 1 controls azimuth.
        #
        # Note range becomes +45 to -45 degrees.
        # Direction flipped so knob motion matches cannon azimuth.
        elif message.channel == 1:
            self._target_azimuth = self._map_midi_note(
                message.note,
                45.0,
                -45.0,
            )

        else:
            return


        # Tell Kit's update loop that MIDI aiming data changed.
        self._midi_aim_dirty = True

# Commenting-out these debug lines so they don't fill up the stdout.
#        print(
#            f"[MIDI] "
#            f"channel={message.channel} "
#            f"note={message.note} "
#            f"azimuth={self._azimuth:.1f} "
#            f"altitude={self._altitude:.1f}"
#        )



    def _map_midi_note(self, note, out_min, out_max):
        # Clamp the incoming note to the expected SQ-1 range.
        #
        # max() prevents values below NOTE_MIN.
        # min() prevents values above NOTE_MAX.
        note = max(NOTE_MIN, min(NOTE_MAX, note))


        # Normalize the MIDI value into the range 0.0 through 1.0.
        #
        # NOTE_MIN  -> t = 0.0
        # NOTE_MAX  -> t = 1.0
        t = (note - NOTE_MIN) / (NOTE_MAX - NOTE_MIN)


        # Convert the normalized value into the desired angle range.
        #
        # Example for azimuth (direction flipped, as noted above):
        #
        # t = 0.0 -> 45 degrees
        # t = 0.5 ->   0 degrees
        # t = 1.0 -> -45 degrees
        return out_min + t * (out_max - out_min)



    def _on_update(self, event):
        # Kit calls this method repeatedly through the update event stream.
        #
        # Docs: NVIDIA Kit Update Events
        # https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/events.html
        
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            return


        # MIDI messages are received on Mido's callback thread.
        # Actual USD changes happen here in Kit's update loop.
        if self._midi_aim_dirty:
            self._update_cannon_aim()
            self._midi_aim_dirty = False


        # ------------------------------------------------------------
        # SMOOTH CANNON SLEW
        # ------------------------------------------------------------

        # Instead of instantly jumping to the MIDI-defined target, move a fraction
        # of the remaining distance toward the target every update.
        #
        # 0.1 means "move 10% of the remaining distance this frame."
        #
        # NOTE:
        # This is frame-rate dependent. A future improvement might use
        # event.payload["dt"] to specify an angular speed in degrees/sec.
        slew_speed = 0.1


        self._azimuth += (
            self._target_azimuth - self._azimuth
        ) * slew_speed


        self._altitude += (
            self._target_altitude - self._altitude
        ) * slew_speed


        # Apply the newly calculated angles to the USD pivot transforms.
        self._update_cannon_aim()


        # ------------------------------------------------------------
        # PROJECTILE LIFETIME
        # ------------------------------------------------------------

        # Projectiles are automatically removed after ten real-world seconds.
        lifetime = 10.0

        # time.monotonic() is designed for measuring elapsed time.
        # Unlike the system clock, it will not jump backward if the computer's
        # date/time changes.
        now = time.monotonic()

        expired = []

        for path, birth_time in self._projectiles.items():
            if now - birth_time >= lifetime:
                expired.append(path)


        # Remove projectiles in a separate loop.
        #
        # Modifying a Python dictionary while iterating over that same
        # dictionary would raise an error.
        for path in expired:
            stage.RemovePrim(path)
            del self._projectiles[path]

            print(
                f"[proctor.block_lab] "
                f"Deleted expired projectile {path}"
            )



    # ------------------------------------------------------------
    # CREATE CANNON
    # ------------------------------------------------------------

    def _create_cannon(self):
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            print("[proctor.block_lab] No USD stage is open")
            return


        # ------------------------------------------------------------
        # CANNON TRANSFORM HIERARCHY
        # ------------------------------------------------------------
        #
        # /World/Cannon
        #     /AzimuthPivot
        #         /CannonBase
        #         /AltitudePivot
        #             /Barrel
        #             /Muzzle
        #
        # Rotating AzimuthPivot rotates everything below it.
        # Rotating AltitudePivot rotates Barrel and Muzzle.
        #
        # Docs: OpenUSD UsdGeomXformable
        # https://openusd.org/release/api/class_usd_geom_xformable.html


        # Root transform for the whole cannon.
        cannon = UsdGeom.Xform.Define(
            stage,
            "/World/Cannon"
        )

        cannon_xform = UsdGeom.XformCommonAPI(cannon)

        # Stage is Y-up. I'm still getting used to that. :P
        # Move cannon away from the tower along -X.
        cannon_xform.SetTranslate(
            (-180.0, 2.0, 0.0)
        )


        # Rotates left/right around the vertical Y axis.
        azimuth_pivot = UsdGeom.Xform.Define(
            stage,
            "/World/Cannon/AzimuthPivot",
        )


        # Simple cannon base.
        cannon_base = UsdGeom.Cube.Define(
            stage,
            "/World/Cannon/AzimuthPivot/CannonBase",
        )

        base_xform = UsdGeom.XformCommonAPI(
            cannon_base
        )

        base_xform.SetTranslate(
            (0.0, 0.0, 0.0)
        )

        cannon_base.CreateSizeAttr(4.0)


        # Altitude pivot is a child of AzimuthPivot.
        altitude_pivot = UsdGeom.Xform.Define(
            stage,
            "/World/Cannon/AzimuthPivot/AltitudePivot",
        )


        # Create the barrel as a cylinder.
        barrel = UsdGeom.Cylinder.Define(
            stage,
            "/World/Cannon/AzimuthPivot/AltitudePivot/Barrel",
        )

        barrel.CreateRadiusAttr(1.5)
        barrel.CreateHeightAttr(12.0)

        # USD cylinders can explicitly choose their longitudinal axis.
        # Our barrel points along local +X.
        barrel.CreateAxisAttr("X")

        barrel_xform = UsdGeom.XformCommonAPI(
            barrel
        )


        # Cylinder is centered around its origin.
        #
        # Moving its center puts its back near X=0 and its front
        # near X=12 relative to AltitudePivot.
        barrel_xform.SetTranslate(
            (6.0, 0.0, 0.0)
        )


        # The muzzle is an empty transform used as a reference point.
        #
        # Because it is a child of AltitudePivot, its world position and
        # orientation automatically follow the cannon's aim.
        muzzle = UsdGeom.Xform.Define(
            stage,
            "/World/Cannon/AzimuthPivot/AltitudePivot/Muzzle",
        )

        muzzle_xform = UsdGeom.XformCommonAPI(
            muzzle
        )

        muzzle_xform.SetTranslate(
            (14.0, 0.0, 0.0)
        )

        print("[proctor.block_lab] Created cannon")


    # ------------------------------------------------------------
    # CANNON AIM
    # ------------------------------------------------------------

    def _update_cannon_aim(self):
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            return


        # Retrieve the two transform pivots from the USD Stage.
        azimuth_prim = stage.GetPrimAtPath(
            "/World/Cannon/AzimuthPivot"
        )

        altitude_prim = stage.GetPrimAtPath(
            "/World/Cannon/AzimuthPivot/AltitudePivot"
        )


        # If the cannon has not been created yet, there is nothing to aim.
        if not azimuth_prim.IsValid():
            return

        if not altitude_prim.IsValid():
            return


        azimuth_xform = UsdGeom.XformCommonAPI(
            azimuth_prim
        )

        altitude_xform = UsdGeom.XformCommonAPI(
            altitude_prim
        )


        # Rotation around Y gives horizontal azimuth.
        azimuth_xform.SetRotate(
            (0.0, self._azimuth, 0.0),
            UsdGeom.XformCommonAPI.RotationOrderXYZ,
        )


        # The barrel points along local +X.
        # Rotating around Z tilts +X toward or away from +Y,
        # giving cannon elevation.
        altitude_xform.SetRotate(
            (0.0, 0.0, self._altitude),
            UsdGeom.XformCommonAPI.RotationOrderXYZ,
        )

# Commenting-out these debug lines so they don't fill up the stdout.
#        print(
#            f"[proctor.block_lab] "
#            f"Azimuth={self._azimuth:.1f} "
#            f"Altitude={self._altitude:.1f}"
#        )



    # ------------------------------------------------------------
    # CREATE PROJECTILE
    # ------------------------------------------------------------

    def _create_projectile(self, position, velocity):
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            print("[proctor.block_lab] No USD stage is open")
            return


        # Parent transform keeps generated projectiles organized.
        UsdGeom.Xform.Define(
            stage,
            "/World/Projectiles"
        )


        # Give each projectile a unique USD name.
        self._projectile_counter += 1

        projectile_path = (
            f"/World/Projectiles/"
            f"Projectile_{self._projectile_counter:04d}"
        )


        # Create the projectile geometry.
        sphere = UsdGeom.Sphere.Define(
            stage,
            projectile_path
        )

        sphere.CreateRadiusAttr(1.8)


        # Place its center at the calculated muzzle position.
        xform_api = UsdGeom.XformCommonAPI(
            sphere
        )

        xform_api.SetTranslate(position)


        # ------------------------------------------------------------
        # USD / PHYSX RIGID BODY
        # ------------------------------------------------------------
        #
        # CollisionAPI: Gives the sphere collision geometry.
        #
        # RigidBodyAPI: Makes the sphere dynamically simulated.
        #
        # MassAPI: Defines its physical mass.
        #
        # Docs: NVIDIA Rigid Body Physics
        # https://docs.omniverse.nvidia.com/kit/docs/asset-requirements/latest/capabilities/physics_bodies/physics_rigid_bodies/capability-physics_rigid_bodies.html

        UsdPhysics.CollisionAPI.Apply(
            sphere.GetPrim()
        )

        UsdPhysics.RigidBodyAPI.Apply(
            sphere.GetPrim()
        )

        mass_api = UsdPhysics.MassAPI.Apply(
            sphere.GetPrim()
        )

        mass_api.CreateMassAttr(200.0)


        # Get the rigid-body schema so we can set initial velocity.
        rigid_body = UsdPhysics.RigidBodyAPI(
            sphere.GetPrim()
        )


        # USD rigid-body velocity expects a Vec3f.
        #
        # The firing calculation uses Vec3d, so convert
        # the three components to float values.
        velocity_vec = Gf.Vec3f(
            float(velocity[0]),
            float(velocity[1]),
            float(velocity[2]),
        )

        rigid_body.CreateVelocityAttr(
            velocity_vec
        )


        # Record when the projectile was created so _on_update()
        # can remove it after its lifetime expires.
        self._projectiles[projectile_path] = (
            time.monotonic()
        )

        print(
            f"[proctor.block_lab] Created {projectile_path}"
        )


    # ------------------------------------------------------------
    # CANNON FIRE
    # ------------------------------------------------------------

    def _fire_cannon(self):
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            print("[proctor.block_lab] No USD stage is open")
            return


        # Find our reference transform at the end of the barrel.
        muzzle_prim = stage.GetPrimAtPath(
            "/World/Cannon/AzimuthPivot/AltitudePivot/Muzzle"
        )

        if not muzzle_prim.IsValid():
            print("[proctor.block_lab] No muzzle found")
            return


        # Treat the muzzle prim as a transformable USD object.
        xformable = UsdGeom.Xformable(
            muzzle_prim
        )


        # ------------------------------------------------------------
        # LOCAL SPACE -> WORLD SPACE
        # ------------------------------------------------------------
        #
        # The muzzle itself only knows its local transform.
        #
        # ComputeLocalToWorldTransform() combines:
        #
        # Cannon
        #   -> AzimuthPivot
        #       -> AltitudePivot
        #           -> Muzzle
        #
        # into one world-space transformation matrix.
        #
        # Docs: OpenUSD UsdGeomXformable
        # https://openusd.org/release/api/class_usd_geom_xformable.html

        world_transform = (
            xformable.ComputeLocalToWorldTransform(
                Usd.TimeCode.Default()
            )
        )


        # Extract the translation component of the matrix.
        # This gives the muzzle's actual position in world coordinates.
        muzzle_position = (
            world_transform.ExtractTranslation()
        )


        # Our barrel was constructed so local +X means "forward."
        local_forward = Gf.Vec3d(
            1.0,
            0.0,
            0.0
        )


        # TransformDir() transforms a direction rather than a position.
        #
        # The cannon's rotations affect the vector, but the cannon's
        # translation does not.
        #
        # This is how the projectile automatically follows
        # azimuth and altitude.
        world_forward = world_transform.TransformDir(
            local_forward
        )


        # Force the direction vector to length 1.
        #
        # This ensures projectile_speed determines the magnitude
        # independently of the transform.
        world_forward.Normalize()

        # ------------------------------------------------------------
        # PROJECTILE SPEED
        # ------------------------------------------------------------
        projectile_speed = 500.0

        velocity = (
            world_forward * projectile_speed
        )


        self._create_projectile(
            muzzle_position,
            velocity,
        )


        print(
            "[proctor.block_lab] Muzzle world position: "
            f"{muzzle_position}"
        )

        print(
            "[proctor.block_lab] Projectile velocity: "
            f"{velocity}"
        )

        print(
            "[proctor.block_lab] cannon fired"
        )


    # ------------------------------------------------------------
    # CREATE THE TOWER
    # ------------------------------------------------------------

    def _create_round_tower(self):
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            print("[proctor.block_lab] no USD stage is open")
            return


        UsdGeom.Xform.Define(
            stage,
            "/World"
        )

        UsdGeom.Xform.Define(
            stage,
            "/World/Tower"
        )


        # Tower construction parameters.
        levels = 32
        bricks_per_level = 16
        radius = 12.0
        brick_height = 1.0
        
        for level in range(levels):

            y = 0.5 + level * brick_height


            # Divide one complete circle (2*pi radians) evenly among
            # all bricks in the current course.
            angle_step = (
                2.0 * math.pi / bricks_per_level
            )


            # Alternate courses by half a brick position to create
            # a running-bond masonry pattern.
            if level % 2 == 0:
                angle_offset = 0.0
            else:
                angle_offset = angle_step / 2.0


            for i in range(bricks_per_level):

                angle = (
                    i * angle_step + angle_offset
                )


                # Convert polar coordinates around the tower into
                # Cartesian X/Z coordinates.
                x = radius * math.cos(angle)
                z = radius * math.sin(angle)


                # Give each brick a unique name.
                path = (
                    f"/World/Tower/"
                    f"Brick_{level:04d}_{i:04d}"
                )


                brick = UsdGeom.Cube.Define(
                    stage,
                    path
                )

                brick.CreateSizeAttr(2.0)


                xform_api = UsdGeom.XformCommonAPI(
                    brick
                )


                # math.sin()/cos() use radians.
                # USD's SetRotate() values here are degrees.
                angle_deg = math.degrees(angle)


                # Rotate the long dimension of each brick so it follows
                # the tangent of the circular tower wall.
                xform_api.SetRotate(
                    (0.0, -angle_deg - 90.0, 0.0),
                    UsdGeom.XformCommonAPI.RotationOrderXYZ,
                )


                xform_api.SetTranslate(
                    (x, y, z)
                )

                xform_api.SetScale(
                    (2.0, 0.5, 1.0)
                )


                # Make every brick a colliding dynamic rigid body.
                #
                # Docs: NVIDIA Rigid Body Physics
                # https://docs.omniverse.nvidia.com/kit/docs/asset-requirements/latest/capabilities/physics_bodies/physics_rigid_bodies/capability-physics_rigid_bodies.html
                
                UsdPhysics.CollisionAPI.Apply(
                    brick.GetPrim()
                )

                UsdPhysics.RigidBodyAPI.Apply(
                    brick.GetPrim()
                )


                # This is a PhysX-specific API rather than one of the
                # generic OpenUSD physics schemas.
                #
                # Increasing solver position iterations improves contact
                # stability in the heavily loaded lower courses of the tower.
                physx_body = (
                    PhysxSchema.PhysxRigidBodyAPI.Apply(
                        brick.GetPrim()
                    )
                )

                physx_body.CreateSolverPositionIterationCountAttr(
                    32
                )
        

    # ------------------------------------------------------------
    # CREATE THE GROUND
    # ------------------------------------------------------------

    def _create_ground(self):
        stage = omni.usd.get_context().get_stage()

        if stage is None:
            print("[proctor.block_lab] no USD stage is open")
            return


        UsdGeom.Xform.Define(
            stage,
            "/World"
        )


        # Ground is a large flattened cube.
        ground = UsdGeom.Cube.Define(
            stage,
            "/World/Ground"
        )

        ground.CreateSizeAttr(2.0)


        xform_api = UsdGeom.XformCommonAPI(
            ground
        )


        xform_api.SetTranslate(
            (0.0, -0.5, 0.0)
        )

        xform_api.SetScale(
            (200.0, 0.5, 200.0)
        )


        # Ground gets CollisionAPI but NOT RigidBodyAPI
        # so it behaves as static collision geometry.
        UsdPhysics.CollisionAPI.Apply(
            ground.GetPrim()
        )


        print(
            "[proctor.block_lab] created /World/Ground"
        )


    # ------------------------------------------------------------
    # EXTENSION SHUTDOWN
    # ------------------------------------------------------------

    def on_shutdown(self):
        # on_shutdown() is called when Kit disables/unloads the extension.
        #
        # Clean up subscriptions and external resources here.
        #
        # Docs: NVIDIA Kit Extensions
        # https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/extensions.html


        # Unsubscribe from keyboard events.
        if self._keyboard_sub_id is not None:
            self._input.unsubscribe_to_keyboard_events(
                self._keyboard,
                self._keyboard_sub_id,
            )


        # Close the physical MIDI input port.
        if self._midi_port is not None:
            self._midi_port.close()


        self._midi_port = None

        self._keyboard_sub_id = None
        self._keyboard = None
        self._app_window = None
        self._input = None
        self._window = None


        # Releasing this subscription object stops _on_update().
        self._update_subscription = None


        print("[proctor.block_lab] Extension shutdown")
