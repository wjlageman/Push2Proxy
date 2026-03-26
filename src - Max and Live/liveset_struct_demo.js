"use strict"
post('==== Compiling JS liveset_struct_demo\n');

// liveset_struct_demo.js
// Demo harness for Tracks + demo JSON definitions.

autowatch = 1;

inlets = 1;
outlets = 2;

var redring_location = [0, 0, 8, 8];

// Start the display of a liveset
function display_liveset()
{
    // Get the data from LOM
    get_tracks();
    get_return_tracks();
    get_scenes();
}

// Incoming json data
function liveset(key, json)
{
    switch (key) {
        case 'tracks':
            Liveset.tracks = JSON.parse(json);
            for (let i = 0; i < Liveset.tracks.length; i++)
            {
                let track = Liveset.tracks[i];
                if (track.type == 'track')
                {
                    get_clips(track["index"], track["visible_track_index"]);
                }
            }
            break;
        case 'clips':
            let obj = JSON.parse(json);
            Liveset.tracks[obj['index']]['clips'] = obj["clips"];
            break;
        case 'return_tracks':
            Liveset.returnTracks = JSON.parse(json);
            break;
        case 'scenes':
            Liveset.scenesCount = JSON.parse(json)["count"];
            Liveset.tracksCount = Liveset.tracks.length;
            Liveset.returnTracksCount = Liveset.returnTracks.length;
            Liveset.totalTracksCount = Liveset.tracksCount + Liveset.returnTracksCount;
            
            outlet(1, Liveset.tracksCount, Liveset.returnTracksCount, Liveset.totalTracksCount, Liveset.scenesCount)

            var startTime = new Date().getTime();
            
            Liveset.display();

            var GFX = new Global("GFX")
            var gfx = GFX.gfx;
            Liveset.draw_redring(gfx, redring_location[0], redring_location[1], redring_location[2], redring_location[3]);

            // Render the result
            gfx.render();

            var endTime = new Date().getTime();
            post("==== Drawing time: " + (endTime - startTime) + " ms\n");
            break;
        default:
            post("ERROR", "The first parameter must be 'tracks', 'clips', 'return_tracks' or scenes, but it is: '" + key + "'.");
            break;
    }
}

function redring(json)
{
    redring_location = JSON.parse(json);
    //post('REDRING', 'PARSED', JSON.stringify(redring_location), '\n');
    outlet(0, 'liveset');
}

function get_tracks()
{
    var songApi = new LiveAPI("live_set");
    var visible_tracks = songApi.get("visible_tracks");

    let tracks = [];
    var index = 0;

    for (var i = 0; i < visible_tracks.length / 2; i++)
    {
        var trackId = visible_tracks[i * 2 + 1];
        var trackApi = new LiveAPI("id", trackId);

        var name = trackApi.get("name");
        var color = trackApi.get("color_index");

        let obj = {
            "index":               index,
            "type":                'track',
            "visible_track_index": i,
            "id":                  trackId,
            "name":                name,
            "color":               color
        }
        tracks.push(obj)
        index++;

        // Chains (requires show_chains to exist)
        var is_showing_chains = trackApi.get("is_showing_chains")[0];
        if (is_showing_chains > 0)
        {
            index = get_chains(trackApi, tracks, index);
        }
    }

    let json = JSON.stringify(tracks);
    outlet(0, 'json', 'liveset', 'tracks', json);
}

function get_chains(api, tracks, index, indent = '')
{
    let devices = api.get('devices')
    for (let d = 0; d < devices.length / 2; d++)
    {
        let api2 = new LiveAPI('id', devices[d * 2 + 1])
        let can_have_chains2 = api2.get('can_have_chains')
        let is_showing_chains2 = (can_have_chains2 > 0) ? api2.get('is_showing_chains') : 0
        if (is_showing_chains2 > 0)
        {
            let chains = api2.get('chains')
            for (let c = 0; c < chains.length / 2; c++)
            {
                let api3 = new LiveAPI('id', chains[c * 2 + 1])
                let name3 = api3.get('name');
                let color3 = api3.get('color_index')
                let obj = {
                    "index":               index,
                    "type":                'chain',
                    "id":                  chains[c * 2 + 1],
                    "name":                name3,
                    "color":               color3
                };
                tracks.push(obj);
                index++;
                index = get_chains(api3, tracks, index, '    ');
            }
        }
    }
    return index;
}

function get_clips(index, visible_track_index)
{
    let clips = [];
    let trackApi = new LiveAPI("live_set visible_tracks " + visible_track_index.toString());
    var clip_slots = trackApi.get("clip_slots");
    for (var s = 0; s < clip_slots.length / 2; s++)
    {
        var slotId = clip_slots[s * 2 + 1];
        var slotApi = new LiveAPI("id", slotId);

        var clip = slotApi.get("clip"); // ["id", <clipId>] or ["id", 0]
        let obj = null;
        if (clip && clip.length >= 2 && clip[1] != "0")
        {
            var clipApi = new LiveAPI("id", clip[1]);
            obj = {
                "name":  clipApi.get("name"),
                "color": clipApi.get("color_index")
            }
        }
        clips.push(obj);
    }

    let obj = {
        "index": index,
        "clips": clips
    }

    let json = JSON.stringify(obj);
    outlet(0, 'json', 'liveset', 'clips', json);
}

function get_return_tracks()
{
    let tracks = [];
    let api = new LiveAPI("live_set")
    let return_tracks = api.get('return_tracks');
    for (let i = 0; i < return_tracks.length / 2; i++)
    {
        var trackId = return_tracks[i * 2 + 1];
        var trackApi = new LiveAPI("id", trackId);

        var name = trackApi.get("name");
        var color = trackApi.get("color_index");
        let obj = {
            "index":               i,
            "type":                'return_track',
            "name":                name,
            "color":               color
        }
        tracks.push(obj)
    }

    let json = JSON.stringify(tracks);
    outlet(0, 'json', 'liveset', 'return_tracks', json);
}

function get_scenes()
{
    var songApi = new LiveAPI("live_set");
    var scenes = songApi.get("scenes");
    let obj = { "count": scenes.length / 2 };
    let json = JSON.stringify(obj);
    outlet(0, 'json', 'liveset', 'scenes', json);
}


// Liveset class
var Liveset = (function ()
{
    function Liveset()
    {
        // static only
    }

    Liveset.tracksCount = 0;
    Liveset.returnTracksCount = 0;
    Liveset.totalTracksCount = 0;
    Liveset.scenesCount = 0;

    // Layout / drawing constants (moved into class)
    Liveset.lcdTop = 0;
    Liveset.lcdLeft = 0;
    Liveset.lcdWidth = 960;
    Liveset.lcdHeight = 160;

    Liveset.offsetTop = 0;
    Liveset.offsetLeft = 2;
    Liveset.offsetRight = 2;
    Liveset.offsetBottom = 0;

    Liveset.canvasColor = [0, 0, 0];
    Liveset.trueColor = [0.09, 0.09, 0.09];

    Liveset.totalWidth = 0;
    Liveset.returnWidth = 25;
    Liveset.gapWidth = 15;
    Liveset.trackWidth = 0;

    Liveset.pointerHeight = 0;
    Liveset.trackYpos = 0;
    Liveset.trackHeight = 20;
    Liveset.trackLineHeight = 2;

    Liveset.clipYpos = 0;
    Liveset.clipHeight = 0;


    Liveset.tracks = [];
    Liveset.returnTracks = [];

    Liveset.display = function ()
    {
        // Start drawing
        post("==== LiveSet DEMO START DRAWING\n");

        post("tracksCount:", Liveset.tracksCount, "\n");
        post("returnTracksCount:", Liveset.returnTracksCount, "\n");
        post("totalTracksCount:", Liveset.totalTracksCount, "\n");
        post("scenesCount:", Liveset.scenesCount, "\n");

        var GFX = new Global("GFX")
        var gfx = GFX.gfx;
        Liveset.draw_base(gfx);
        for (let i = 0; i < Liveset.tracks.length; i++)
        {
            Liveset.draw_track(gfx, i, Liveset.tracks[i]);
        }
        for (let i = 0; i < Liveset.returnTracks.length; i++)
        {
            Liveset.draw_return_track(gfx, Liveset.returnTracks[i]);
        }
        Liveset.draw_rest(gfx);

        post("==== LiveSet DEMO DRAWING READY\n");
    };

    // Start strawing
    Liveset.draw_base = function (gfx)
    {
        Liveset.totalWidth = Liveset.lcdWidth - Liveset.offsetLeft - Liveset.offsetRight;

        gfx.color(Liveset.canvasColor);
        gfx.rectangle(Liveset.lcdLeft, Liveset.lcdTop, Liveset.lcdWidth, Liveset.lcdHeight);
        gfx.fill();

        gfx.color(Liveset.trueColor);
        gfx.rectangle(
            Liveset.lcdLeft + Liveset.offsetLeft,
            Liveset.lcdTop + Liveset.offsetTop,
            Liveset.totalWidth,
            Liveset.lcdHeight - Liveset.offsetTop - Liveset.offsetBottom
        );
        gfx.fill();

        Liveset.returnWidth = 25;
        Liveset.gapWidth = 15;

        // Make gap wider when there are less then 8 tracks
        if (Liveset.totalTracksCount < 8)
        {
            Liveset.gapWidth = (Liveset.totalWidth - Liveset.gapWidth - Liveset.returnTracksCount * Liveset.returnWidth) -
                Liveset.tracksCount * ((Liveset.totalWidth - Liveset.gapWidth - Liveset.returnTracksCount * Liveset.returnWidth) / (8 - Liveset.returnTracksCount));
        }

        Liveset.trackWidth = (Liveset.totalWidth - Liveset.gapWidth - Liveset.returnTracksCount * Liveset.returnWidth) / (Liveset.tracksCount || 1);

        Liveset.pointerHeight = 0;
        Liveset.trackYpos = Liveset.offsetTop + Liveset.pointerHeight;
        Liveset.trackHeight = 20;
        Liveset.trackLineHeight = 2;

        Liveset.clipYpos = Liveset.trackYpos + Liveset.trackHeight + Liveset.trackLineHeight;
        Liveset.clipHeight = (Liveset.lcdHeight - Liveset.offsetBottom - Liveset.clipYpos) / (Liveset.scenesCount || 1);
    };


    // ---------------------------------------------------------------------
    // Draw a normal track (0-based index within normal tracks)
    // track object shape assumed:
    //   { id, name, color, clips:[ {color, name?} | null ... ] }
    // ---------------------------------------------------------------------
    Liveset.draw_track = function (gfx, index, track)
    {
        var trackXpos = Math.round(Liveset.offsetLeft + (index * Liveset.trackWidth));

        // Track header rectangle
        var color = gfx.color("L" + track["color"]);
        gfx.rectangle(trackXpos, Liveset.trackYpos, Liveset.trackWidth, Liveset.trackHeight);
        gfx.fill();

        // Track label
        gfx.color((color[0] + color[1] + color[2] > 0.8) ? "black" : [0.7, 0.7, 0.7]);
        gfx.move_to(trackXpos + 3, Liveset.trackYpos + 15);
        var name = track["name"];
        if (Liveset.tracksCount > 24 && name)
        {
            name = String(name).slice(0, 2);
        }
        gfx.show_label(name, 12, Liveset.trackWidth - 6, 1, true);

        // Clips
        var clips = track["clips"];
        if (clips && clips.length)
        {
            for (var j = 0; j < clips.length; j++)
            {
                var clip = clips[j];
                color = gfx.color(clip ? ("D" + clip["color"]) : Liveset.trueColor);

                gfx.rectangle(trackXpos, Liveset.clipYpos + j * Liveset.clipHeight, Liveset.trackWidth, Liveset.clipHeight);
                gfx.fill();

                let h = Liveset.clipHeight;
                if (h > 18) h = 18;
                if (clip && clip["name"])
                {
                    gfx.color((color[0] + color[1] + color[2] > 0.8) ? "black" : [0.7, 0.7, 0.7]);
                    gfx.move_to(trackXpos + 3 + h * 0.6, Liveset.clipYpos + j * Liveset.clipHeight + Liveset.clipHeight * 0.7);
                    gfx.show_label(clip["name"], h * 0.6, Liveset.trackWidth - 5 - h * 0.7, 1, true);
                }
            }
        }

        // Border around track column
        gfx.color("black");
        gfx.set_line_width(1);
        gfx.rectangle(trackXpos, Liveset.trackYpos, Liveset.trackWidth, Liveset.lcdHeight - Liveset.offsetBottom - Liveset.trackYpos);
        gfx.stroke();
    };

    // ---------------------------------------------------------------------
    // Draw a return track (0-based index within return tracks)
    // track object shape assumed:
    //   { id, name, color }
    // ---------------------------------------------------------------------
    Liveset.draw_return_track = function (gfx, track)
    {
        let offsetReturns = Math.round(Liveset.offsetLeft + (Liveset.tracksCount * Liveset.trackWidth) + Liveset.gapWidth)
        var returnXpos = Math.round(offsetReturns + (track['index'] * Liveset.returnWidth));

        // Header rectangle
        var color = gfx.color("L" + track["color"]);
        gfx.rectangle(returnXpos, Liveset.trackYpos, Liveset.returnWidth, Liveset.trackHeight);
        gfx.fill();

        // Label: first char
        gfx.color((color[0] + color[1] + color[2] > 0.8) ? "black" : [0.7, 0.7, 0.7]);
        gfx.move_to(returnXpos + 8, Liveset.trackYpos + 15);
        let name = String(track["name"]);
        gfx.show_label(name[0], 11, Liveset.returnWidth - 6, 1, true);

        // Border
        gfx.color("black");
        gfx.set_line_width(1);
        gfx.rectangle(returnXpos, Liveset.trackYpos, Liveset.returnWidth, Liveset.lcdHeight - Liveset.offsetBottom - Liveset.trackYpos);
        gfx.stroke();
    };

    Liveset.draw_rest = function (gfx)
    {
        // Gap topline
        gfx.color("black");
        gfx.rectangle(
            Liveset.offsetLeft + Liveset.trackWidth * Liveset.tracksCount,
            Liveset.trackYpos - 1,
            Liveset.gapWidth,
            2
        );
        gfx.fill();

        // All tracks underline (including gap)
        gfx.color("black");
        gfx.rectangle(
            Liveset.offsetLeft,
            Liveset.trackYpos + Liveset.trackHeight,
            Liveset.totalTracksCount * Liveset.trackWidth + Liveset.gapWidth,
            Liveset.trackLineHeight
        );
        gfx.fill();
    }

    Liveset.draw_redring = function (gfx, xPos, yPos, width=8, height=8)
    {
        // Make sure redringX and redringW are within bounds
        if (xPos < 0)
        {
            xPos = 0;
        }
        else if (xPos > Liveset.totalTracksCount - 1)
        {
            xPos = Liveset.totalTracksCount - 1;
        }

        if (width < 0)
        {
            width = 0;
        }
        else if (xPos + width > Liveset.totalTracksCount - 1)
        {
            width = Liveset.totalTracksCount - xPos;
        }

        // Calculate the start
        var redringXpos = Liveset.offsetLeft;
        if (xPos < Liveset.tracksCount)
        {
            redringXpos += xPos * Liveset.trackWidth;
        }
        else
        {
            redringXpos += Liveset.tracksCount * Liveset.trackWidth + Liveset.gapWidth;
            redringXpos += (xPos - Liveset.tracksCount) * Liveset.returnWidth;
        }

        // Calculate the width
        var redringWidth = 0;
        var togo = width;

        if (xPos + width >= Liveset.totalTracksCount)
        {
            redringWidth = Liveset.totalWidth - redringXpos;
        }
        else if (xPos < Liveset.tracksCount)
        {
            var n = Liveset.tracksCount - xPos;
            if (n > width)
            {
                n = width;
            }

            redringWidth += n * Liveset.trackWidth;
            togo -= n;

            if (togo > 0)
            {
                redringWidth += Liveset.gapWidth + togo * Liveset.returnWidth;
            }
        }

        // Crisp outer edge (dominant)
        gfx.color([1, 0, 0, 1]);
        gfx.set_line_width(5);
        gfx.rectangle(redringXpos, Liveset.clipYpos + (yPos * Liveset.clipHeight), redringWidth, height * Liveset.clipHeight);
        gfx.stroke();

        // Inner "boost" (subtle, keeps illusion of super-red)
        gfx.color([1, 0.07, 0.07, 1]);
        gfx.set_line_width(3);
        gfx.rectangle(redringXpos + 1, Liveset.clipYpos + (yPos * Liveset.clipHeight) + 1, redringWidth - 2, height * Liveset.clipHeight - 2);
        gfx.stroke();
    };


    // ---------------------------------------------------------------------
    // Finish drawing: gap topline + underline + render + logging
    // ---------------------------------------------------------------------
    Liveset.finish_drawing = function (label, startTime)
    {
        var gfx = Liveset._gfx;
        if (!gfx)
        {
            return;
        }

        // Optional (if caller doesn't pass them)
        Liveset._label = (label === undefined || label === null) ? Liveset._label : String(label);
        Liveset._startTime = (startTime === undefined || startTime === null) ? Liveset._startTime : (startTime | 0);

        // Gap topline
        gfx.color("black");
        gfx.rectangle(Liveset.offsetLeft + Liveset.trackWidth * Liveset.tracksCount, Liveset.trackYpos - 1, Liveset.gapWidth, 2);
        gfx.fill();

        // All tracks underline (include gap)
        gfx.color("black");
        gfx.rectangle(Liveset.offsetLeft, Liveset.trackYpos + Liveset.trackHeight, Liveset.totalTracksCount * Liveset.trackWidth + Liveset.gapWidth, Liveset.trackLineHeight);
        gfx.fill();
    };

    return Liveset;
}());


post('==== Compiling JS liveset_struct_demo Done\n');

