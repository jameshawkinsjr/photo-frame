# Photo Frame

A full-screen, randomly shuffled photo album for an old Mac, built for a 2009 iMac
running macOS 10.13 High Sierra.

There is **nothing to install** on the iMac. High Sierra already ships with the
Python and Cocoa (PyObjC) pieces this uses, so it is just a folder of scripts
wrapped in a normal-looking Mac app.

## What it does

- Shows photos from a folder you choose, **including every sub-folder**, at full screen.
- Picks them at random, drawn from `/dev/urandom` rather than a seeded shuffle.
- Prints each photo's **date in the bottom-right corner**, taken from the photo's own
  EXIF data where it has any, and from the file's date where it doesn't.
- Handles libraries of 10,000+ photos comfortably — the folder list is cached, and
  each photo is decoded straight down to screen size instead of at full resolution.
- Turns itself **on and off at set times**, and puts the Mac to sleep in between.

## Installing it on the iMac

Download **Photo Frame.dmg** from this repo's [Releases](https://github.com/jameshawkinsjr/photo-frame/releases) page (or build it yourself, below). Copy it to the iMac — USB stick, AirDrop, shared folder, whatever
suits — and double-click it. A window opens with the app on the left and a shortcut
to your Applications folder on the right: drag one onto the other.

Then open it from Applications. **The first time, right-click the app and choose
Open**, and confirm. The app isn't signed with an Apple developer certificate, so a
plain double-click gets refused the first time; right-click → Open is macOS's way of
saying "yes, I meant it". After that it opens normally.

Once it's copied across you can eject and throw away the disk image.

### The other way

If you'd rather not use the disk image, copy this whole folder over instead, open
**Terminal** (Applications → Utilities), type `sh` followed by a space, then drag
`install.sh` onto the window and press Return. That builds the same app in your home
Applications folder. Add a path to put it elsewhere:

```sh
sh install.sh /Applications
```

### Rebuilding the disk image

On any Mac, from this folder:

```sh
sh build_dmg.sh
```

## First run

Open Photo Frame. The Settings window appears on its own the first time — click
**Choose Folder…** and pick the folder holding your photos.

The first scan of a large library takes a few seconds to a minute or two, and it runs
in the background: photos start appearing as soon as the first ones are found. After
that the list is cached, so every later start is immediate. The library is quietly
re-scanned every 12 hours, and whenever you press **Rescan Now**.

## Everyday controls

| Key | Does |
| --- | --- |
| `Esc` | Open Settings |
| `Space` | Pause / carry on |
| `←` `→` | Back / forward by hand |
| `D` | Hide or show the date |
| `H` | Show the on-screen reminder of these keys |
| `Cmd-Q` | Quit |

The pointer hides itself while the show is running and comes back when you move the
mouse.

## Settings

**Photos** — the folder, and how many photos were found in it. JPEG, PNG, HEIC, TIFF,
GIF, BMP and common raw formats (CR2, NEF, ARW, DNG and friends) are all included.
Hidden folders are skipped, and if you point it at a Photos library it reads the
originals rather than the thumbnails.

**Playback** — seconds per photo, and the length of the cross-fade between them (set
it to 0 for a hard cut).

*Order* is worth a word:

- **True random** draws from the whole library every single time, so — as with any
  genuinely random draw — a photo can come round again sooner than you might expect.
  The **Avoid repeats within N photos** box is there to take the edge off that without
  giving up the randomness: with 10,000 photos, a window of 200 means you will never
  see the same picture twice inside about an hour, while everything else stays a fair,
  independent draw.
- **Shuffle** deals the whole library like a deck of cards: every photo is shown once,
  then it reshuffles and starts again. Pick this if you would rather see all 10,000
  before any repeats.

**Date caption** — whether to show the date, in which style, and how large.

**Daily schedule** — see below.

**Startup** — two things. *Open Photo Frame automatically* adds it to your login items,
so the frame comes back by itself after a restart or power cut. *Keep the screen saver
from covering the photos* switches the screen saver off for your account, since it
would otherwise slide in over the slideshow; it is on by default, and unticking it
puts the Mac's own default back. Nothing outside Photo Frame's own settings is changed
unless one of these is ticked.

## The daily schedule

Tick **Run only between the times below** and set, for example, on at `08:00` and off
at `22:00`. Times use the 24-hour clock, and an overnight span (on at `20:00`, off at
`06:00`) works fine.

At the **off** time the slideshow stops and, if the box is ticked, Photo Frame puts the
Mac to sleep. While the show is running it holds the Mac and its display awake for you,
so you don't need to change the Energy Saver sleep settings.

**Waking back up needs one extra step.** A sleeping Mac cannot start its own
slideshow, so the wake has to be booked with the Mac's power system. Click
**Wake the Mac Automatically…** in Settings and enter your account password once. That
schedules a daily wake two minutes before your start time — and if the iMac is fully
shut down rather than asleep, it will switch itself on. The line underneath the buttons
always tells you what is currently booked.

Without that step everything else still works; the Mac just sleeps at 22:00 and waits
for you to press a key in the morning.

If you wake the Mac yourself outside the scheduled hours, it gives you five minutes
before sleeping again (adjustable in `config.json`), and it will never sleep while the
Settings window is open.

To check or clear the wake schedule by hand:

```sh
pmset -g sched          # what is booked
sudo pmset repeat cancel # clear it
```

## Where things are kept

`~/Library/Application Support/PhotoFrame/`

- `config.json` — your settings, plain text and safe to edit by hand
- `index.json` — the cached list of photo files
- `photoframe.log` — a short log of starts, stops, scans and skipped files

Deleting any of them is harmless; they are rebuilt.

## Troubleshooting

**Photos on an external drive.** If the drive is unplugged the frame says it is waiting
for the folder and keeps its list of photos; it picks up again by itself when the drive
comes back.

**A photo never appears.** Files that can't be decoded are logged and dropped for that
session. They come back on the next rescan in case the problem was temporary.

**The date looks wrong.** Photos without EXIF data fall back to the file's own date,
which is often the date it was copied rather than the date it was taken. The caption
style can be set to just the year if that reads better.

**Nothing happens when I open it.** Run this in Terminal to see the error directly:

```sh
/usr/bin/python "$HOME/Applications/Photo Frame.app/Contents/Resources/photoframe.py"
```

**It won't sleep / won't wake.** Check `pmset -g sched`, and make sure Energy Saver's
"Wake for network access" isn't the only thing keeping it up.

## Running it without installing

```sh
/usr/bin/python photoframe.py
```

Same app, no bundle — handy for a quick try before installing.

## License

MIT. See [LICENSE](LICENSE).
