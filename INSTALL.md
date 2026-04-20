# Installing Seating Chart Manager

Welcome! This is a quick guide to get the app running on your Mac. It takes about 2 minutes, and most of that is the first-time security step.

## What you'll receive

A single file called `SeatingChartManager.dmg`. This is a standard Mac installer package.

## Step 1 — Install the app

1. Double-click `SeatingChartManager.dmg` to open it. A window will appear showing the app icon and an arrow pointing to your Applications folder.
2. **Drag the app icon onto the Applications folder** in that window.
3. Close the installer window.
4. Eject the installer from the sidebar in Finder (look for the small eject arrow next to `Seating Chart Manager`).

You can now throw away the `.dmg` file. The app is installed.

## Step 2 — First launch (important!)

Because this app was built for your school and isn't registered with Apple's App Store, macOS will show a security warning the first time you try to open it. This is expected — you need to tell your Mac once that you trust this app.

**Do NOT just double-click the app the first time.** That will show a dead-end error. Instead:

1. Open your Applications folder (the easiest way: click the Finder icon in your Dock, then click "Applications" in the sidebar).
2. Find **Seating Chart Manager**.
3. **Right-click** it (or Control-click if you don't have a right mouse button). A menu appears.
4. Choose **Open** from that menu.
5. A dialog appears saying *"macOS cannot verify the developer of Seating Chart Manager. Are you sure you want to open it?"*
6. Click **Open**.

The app will launch.

**From this point on**, you can open the app normally by double-clicking it in Applications, from Launchpad, or from Spotlight (Cmd+Space, type "seating"). The right-click trick is a one-time step.

## What if I get stuck?

- **"Seating Chart Manager is damaged and can't be opened"** — this sometimes happens if macOS quarantines the downloaded file. Open Terminal (Applications → Utilities → Terminal) and paste this command, then press Enter:
  ```
  xattr -cr /Applications/SeatingChartManager.app
  ```
  Then try the right-click → Open steps again.

- **I can't find the app in Applications** — make sure you dragged the app icon (not the installer window itself) onto the Applications folder. If in doubt, open the `.dmg` again and repeat Step 1.

- **The app shows a rocket icon in the Dock instead of the chair icon** — this means you're running the source code via Terminal, not the installed app. Launch it from Applications instead.

## Your data

Everything you create in the app — classes, students, rounds, layouts — is saved automatically to:

```
~/Library/Application Support/SeatingChartManager/seating_chart.db
```

This is a per-user location. Other accounts on the same Mac have their own separate data. Time Machine backs this up automatically.

If you ever want to move to a new Mac, copying that file to the same location on the new Mac will bring everything with you.

## Updating

When a new version is released, you'll get a new `.dmg`. Drag the new app into Applications to replace the old one — your data stays put at the path above.

---

Questions? Contact [your name / email].