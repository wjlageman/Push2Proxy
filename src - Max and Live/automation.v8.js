"use strict";

post('==== automation.V8.js starts ====\n');

// Path: C:\ProgramData\Ableton\Live 12 Suite\Resources\Max\resources\externals
//////////////////////////////////////////
// Global Variables
//////////////////////////////////////////
autowatch = 1;
// Define inlet and outlet counts
inlets = 1
outlets = 4;

// Outlet indices for communication
var push2Active = 0;
var newFrame = 1;

var outletGfx = 2;
var outletTest = 3;


// Parent object needed to link to Max objects
var thisPatcher = this.patcher;
// Global graphics object, initialized later
var gfx;
var push2;
var wjl_libusb_proxy;
var isGrabbed


function initialize() {
    var startTime = new Date().getTime();
    // Get the jit.mgraphics engine going
    gfx = new JitMgraphics(960, 160);

    var GFX = new Global("GFX")
    GFX.gfx = gfx

    post('TEST', GFX.gfx)

    var isGrabbed = 0
    wjl_libusb_proxy = thisPatcher.getnamed('wjl_libusb_proxy');
    wjl_libusb_proxy.message('blend', isGrabbed ? 1 : 0);
    outlet(push2Active, 'set', isGrabbed);

    // Create the graphics updaters
    var push2View = new DisplayView(gfx, wjl_libusb_proxy);
    var mainView = new DisplayView(gfx, thisPatcher.getnamed('main_pwindow'));
    //var detailView = new DisplayView(gfx, thisPatcher.getnamed('detail_pwindow'), 2 * 120, 0);
    //post('WIDGETS', JSON.stringify(Push2, null, '   '), '\n');
    var endTime = new Date().getTime();
    post("==== Duration of initilizing: ".concat(endTime - startTime, " ms\n"));

    post("==== Duration of initilizing: ".concat(endTime - startTime, " ms\n"));
}


function grabpush2(state) {
    post("wjl_libusb_proxy", wjl_libusb_proxy, '\n');
    if (wjl_libusb_proxy) {
        post("Call Initialize\n");
        initialize();
    }

    isGrabbed = state
    if (wjl_libusb_proxy)
    {
  	    wjl_libusb_proxy.message('blend', isGrabbed ? 1 : 0);
   	    outlet(push2Active, 'set', isGrabbed);
    }
}


//////////////////////////////////////////
//
// Classes
//

//////////////////////////////////////////
//
// class JitMgraphics
//
var JitMgraphics = /** @class */ (function () {
    function JitMgraphics(width, height) {
        var _this = this;
        this.width = width;
        this.height = height;

        // ------------------------------------------------------------------
        // Pixel snapping helpers (avoid color bleeding on rectangles)
        // ------------------------------------------------------------------
        function snapFloor(v) { return Math.floor(v + 0.00001); }
        function snapCeil(v) { return Math.ceil(v - 0.00001); }

        function rectToIntEdges(x, y, w, h)
        {
            var x1 = snapFloor(x);
            var y1 = snapFloor(y);
            var x2 = snapCeil(x + w);
            var y2 = snapCeil(y + h);

            var ww = x2 - x1;
            var hh = y2 - y1;

            if (ww <= 0 || hh <= 0)
            {
                return null;
            }

            return { x: x1, y: y1, w: ww, h: hh };
        }

        // ------------------------------------------------------------------
        // ColorRegistry
        // ------------------------------------------------------------------
        var LIVE_COLOR_INDEX_TO_SCREEN_COLOR = [
            15554872,16737280,8406803,15587900,9764632,40242,47445,52361,29092,4797107,5398749,14768099,16719410,15587900,13702922,
            16724480,5776135,14991872,58929,3382803,29006,48045,27338,23138,11227391,8929883,16730774,8406803,15554872,16737280,
            8406803,15587900,9764632,40242,47445,52361,29092,4797107,5398749,11227391,16719410,29092,15554872,16737280,8406803,
            15587900,9764632,40242,47445,52361,29092,4797107,5398749,14768099,16719410,5398749,13702922,16724480,5776135,14991872,
            58929,3382803,29006,23138,4797107,27338,11227391,14768099,16730774,5776135
        ];


        var LIVE_COLOR_INDEX_TO_SCREEN_COLOR_1 = [ 
            12470061, 13389824, 6699279, 12496432, 7785491, 32296, 37956, 41838, 23171, 3811471, 4345265, 11814582, 13375528, 
            12496432, 10949128, 13379584, 4594694, 11967232, 47143, 2719247, 23102, 38538, 21922, 18510, 8995020, 7157065, 13384568, 
            6699279, 12470061, 13389824, 6699279, 12496432, 7785491, 32296, 37956, 41838, 23171, 3811471, 4345265, 8995020, 
            13375528, 23171, 12470061, 13389824, 6699279, 12496432, 7785491, 32296, 37956, 41838, 23171, 3811471, 4345265, 11814582, 
            13375528, 4345265, 10949128, 13379584, 4594694, 11967232, 47143, 2719247, 23102, 18510, 3811471, 21922, 8995020, 
            11814582, 13384568, 4594694 
        ];

        var LIVE_COLOR_INDEX_TO_SCREEN_COLOR_2 = [ 
            7810332, 8401408, 4203530, 7826718, 4882444, 20249, 23851, 26181, 14674, 2431322, 2699375, 7416946, 8392473, 7826718, 
            6884357, 8395008, 2888196, 7495936, 29465, 1724170, 14631, 24151, 13669, 11569, 5646464, 4464942, 8398155, 4203530, 7810332, 
            8401408, 4203530, 7826718, 4882444, 20249, 23851, 26181, 14674, 2431322, 2699375, 5646464, 8392473, 14674, 7810332, 
            401408, 4203530, 7826718, 4882444, 20249, 23851, 26181, 14674, 2431322, 2699375, 7416946, 8392473, 2699375, 6884357, 
            8395008, 2888196, 7495936, 29465, 1724170, 14631, 11569, 2431322, 13669, 5646464, 7416946, 8398155, 2888196 
        ];

        var LIVE_COLOR_INDEX_TO_SCREEN_COLOR_3 = [ 
            4659985, 5053952, 2495750, 4669714, 2903303, 12047, 14362, 15657, 8753, 1445686, 1645890, 4463172, 5048591, 4669714, 
            4130563, 5050112, 1706754, 4471296, 17679, 995078, 8727, 14388, 8253, 6941, 3348557, 2692123, 5051949, 2495750, 4659985, 
            5053952, 2495750, 4669714, 2903303, 12047, 14362, 15657, 8753, 1445686, 1645890, 3348557, 5048591, 8753, 4659985, 5053952, 
            2495750, 4669714, 2903303, 12047, 14362, 15657, 8753, 1445686, 1645890, 4463172, 5048591, 1645890, 4130563, 5050112, 
            1706754, 4471296, 17679, 995078, 8727, 6941, 1445686, 8253, 3348557, 4463172, 5051949, 1706754 
        ];

        Colors.init_live_colors(LIVE_COLOR_INDEX_TO_SCREEN_COLOR_1, 'L');
        Colors.init_live_colors(LIVE_COLOR_INDEX_TO_SCREEN_COLOR_2, 'D');
        Colors.init_basic_named_colors();

        this.colors = Colors.colors;

        // ------------------------------------------------------------------
        // Wrapper functions in one line
        // ------------------------------------------------------------------
        this.arc = function (cx, cy, radius, startAngle, endAngle) { return _this.gfx.arc(cx, cy, radius, startAngle, endAngle); };

        this.fill = function () { return _this.gfx.fill(); };

        this.line_to = function (x, y) { return _this.gfx.line_to(x, y); };

        this.move_to = function (x, y) { return _this.gfx.move_to(x, y); };

        this.rel_line_to = function (x, y) { return _this.gfx.rel_line_to(x, y); };

        this.rel_move_to = function (x, y) { return _this.gfx.rel_move_to(x, y); };

        // ------------------------------------------------------------------
        // Rectangles:
        // - rectangle(...) now snaps to integer edges internally (default safe UI behavior)
        // - rectangle_float(...) preserves floats for special cases
        // ------------------------------------------------------------------

        // Optional: store last rectangle request for debugging
        this._lastRect = null;
        this._lastRectSnapped = null;

        this.rectangle = function (x, y, width, height)
        {
            _this._lastRect = { x: x, y: y, w: width, h: height };

            var r = rectToIntEdges(x, y, width, height);
            _this._lastRectSnapped = r;

            if (!r)
            {
                return;
            }

            return _this.gfx.rectangle(r.x, r.y, r.w, r.h);
        };

        this.rectangle_float = function (x, y, width, height)
        {
            _this._lastRect = { x: x, y: y, w: width, h: height };
            _this._lastRectSnapped = null;
            return _this.gfx.rectangle(x, y, width, height);
        };

        this.select_font_face = function (font) { return _this.gfx.select_font_face(font); };

        this.set_font_size = function (size) { return _this.gfx.set_font_size(size); };

        this.set_line_width = function (width) { return _this.gfx.set_line_width(width); };

        this.set_source_rgba = function (r, g, b, a) { return _this.gfx.set_source_rgba(r, g, b, a); };

        // Color: accept 'L32', named colors, or [r,g,b] / [r,g,b,a] (assume 0..1)
        this.color = function (color) {
            if (typeof (color) === "string")
            {
                color = Colors.colors[color];
            }

            if (!color)
            {
                _this.gfx.set_source_rgba(1, 0, 1, 1);
                return [1, 0, 1, 1];
            }

            var r = color[0];
            var g = color[1];
            var b = color[2];
            var a = (color.length >= 4) ? color[3] : 1;

            _this.gfx.set_source_rgba(r, g, b, a);
            return [r, g, b, a];
        };

        this.show_text = function (text) { return _this.gfx.show_text(text); };

        this.show_label = function (text, fontSize, maxWidth, maxLines, tailEllipsis)
        {
            if (maxLines === undefined || maxLines === null) { maxLines = 1; }

            var label = new PreparedLabel(text, fontSize, maxWidth, maxLines, tailEllipsis);
            _this.gfx.select_font_face(label.font);
            _this.gfx.set_font_size(label.fontSize);
            return _this.gfx.show_text(label.line1);
        };

        this.stroke = function () { return _this.gfx.stroke(); };

        this.text_measure = function (text) { return _this.gfx.text_measure(text); };

        // Measure text width
        this.measureTextWidth = function (text, font, size) {
            _this.gfx.select_font_face(font);
            _this.gfx.set_font_size(size);
            return _this.gfx.text_measure(text)[0];
        };

        // Render and notify subscribers
        this.render = function () {
            _this.gfx.matrixcalc(_this.gfxMatrix, _this.gfxMatrix);
            _this.notifyGraphicsChanged();
        };

        // Subscription management
        this.subscribeGraphicsChanged = function (subscriber) {
            if (_this.subscribers.indexOf(subscriber) === -1)
            {
                _this.subscribers.push(subscriber);
            }
        };

        this.unsubscribeGraphicsChanged = function (subscriber) {
            var index = _this.subscribers.indexOf(subscriber);
            if (index > -1)
            {
                _this.subscribers.splice(index, 1);
            }
        };

        this.notifyGraphicsChanged = function () {
            for (var i = 0; i < _this.subscribers.length; i++) {
                try {
                    _this.subscribers[i](_this, _this.gfxMatrix);
                }
                catch (error) {
                    post("Error notifying subscriber: " + JSON.stringify(error, null, "    ") + "\n");
                }
            }
            outlet(newFrame, 'b');
        };

        this.subscribers = [];
        this.gfx = new JitterObject("jit.mgraphics", this.width, this.height);
        this.gfxMatrix = new JitterMatrix('Push2', 4, "char", this.width, this.height);
    }
    return JitMgraphics;
}());


var JitMgraphics2 = /** @class */ (function () {
    function JitMgraphics2(width, height) {
        var _this = this;
        this.width = width;
        this.height = height;

        // ColorRegistry
        // ------------------------------------------------------------------
        // Live palette (packed RGB ints) from your list.
        // L0..L68 will be registered on load.
        // ------------------------------------------------------------------

        var LIVE_COLOR_INDEX_TO_SCREEN_COLOR = [
            15554872,16737280,8406803,15587900,9764632,40242,47445,52361,29092,4797107,5398749,14768099,16719410,15587900,13702922,
            16724480,5776135,14991872,58929,3382803,29006,48045,27338,23138,11227391,8929883,16730774,8406803,15554872,16737280,
            8406803,15587900,9764632,40242,47445,52361,29092,4797107,5398749,11227391,16719410,29092,15554872,16737280,8406803,
            15587900,9764632,40242,47445,52361,29092,4797107,5398749,14768099,16719410,5398749,13702922,16724480,5776135,14991872,
            58929,3382803,29006,23138,4797107,27338,11227391,14768099,16730774,5776135];

        //post('COLORS 1', Colors.)
        Colors.init_live_colors(LIVE_COLOR_INDEX_TO_SCREEN_COLOR);
        Colors.init_basic_named_colors();
        
        this.colors = Colors.colors;

        // Wrapper functions in one line
        this.arc = function (cx, cy, radius, startAngle, endAngle) { return _this.gfx.arc(cx, cy, radius, startAngle, endAngle); };

        this.fill = function () { return _this.gfx.fill(); };

        this.line_to = function (x, y) { return _this.gfx.line_to(x, y); };

        this.move_to = function (x, y) { return _this.gfx.move_to(x, y); };

        this.rel_line_to = function (x, y) { return _this.gfx.rel_line_to(x, y); };

        this.rel_move_to = function (x, y) { return _this.gfx.rel_move_to(x, y); };

        this.rectangle = function (x, y, width, height) { return _this.gfx.rectangle(x, y, width, height); };

        this.select_font_face = function (font) { return _this.gfx.select_font_face(font); };

        this.set_font_size = function (size) { return _this.gfx.set_font_size(size); };

        this.set_line_width = function (width) { return _this.gfx.set_line_width(width); };

        this.set_source_rgba = function (r, g, b, a) { return _this.gfx.set_source_rgba(r, g, b, a); };

        this.color = function (color) { 
            if (typeof(color) == 'string')
            {
                /*
                for (let c in Colors.colors)
                {
                    post('COLOR', c, Colors.colors[c], '\n')
                }
                */
                color = Colors.colors[color];
            }
            //post('MGRAPHICS COLOR', color, typeof(color), color[0], color[1], color[2], color[3], '\n')
            _this.gfx.set_source_rgb(color[0], color[1], color[2], 1);
            return color;
        }

        this.show_text = function (text) { return _this.gfx.show_text(text); };

        this.show_label = function (text, fontSize, maxWidth, maxLines, tailEllipsis)
        {
			if (! maxLines)
			{
				maxLines = 1;
			}
            var label = new PreparedLabel(text, fontSize, maxWidth, maxLines, tailEllipsis);
            post('LABEL', text, label.line1, label.line2, label.line1Width, label.line2Width, '\n');
            _this.gfx.select_font_face(label.font)
            _this.gfx.set_font_size(label.fontSize)
            return this.show_text(label.line1);
        }

        this.stroke = function () { return _this.gfx.stroke(); };

        this.text_measure = function (text) { return _this.gfx.text_measure(text); };

        // Measure text width
        this.measureTextWidth = function (text, font, size) {
            _this.gfx.select_font_face(font);
            _this.gfx.set_font_size(size);
            return _this.gfx.text_measure(text)[0]; // Return measured width
        };
        // Render and notify subscribers
        this.render = function () {
            //const startTime = new Date().getTime();
            _this.gfx.matrixcalc(_this.gfxMatrix, _this.gfxMatrix);
            _this.notifyGraphicsChanged();
            //const endTime = new Date().getTime();
            //post(`Render time: ${endTime - startTime} ms\n`);
        };
        // Subscription management
        this.subscribeGraphicsChanged = function (subscriber) {
            if (_this.subscribers.indexOf(subscriber) === -1)
                _this.subscribers.push(subscriber);
        };
        this.unsubscribeGraphicsChanged = function (subscriber) {
            var index = _this.subscribers.indexOf(subscriber);
            if (index > -1)
                _this.subscribers.splice(index, 1);
        };
        this.notifyGraphicsChanged = function () {
            for (var i = 0; i < _this.subscribers.length; i++) {
                try {
                    _this.subscribers[i](_this, _this.gfxMatrix);
                    post('Sunscriber', i, _this.subscribers[i].matrix, JSON.stringify(_this.subscribers[i]), '\n')
                }
                catch (error) {
                    post("Error notifying subscriber: " + JSON.stringify(error, null, "    ") + "\n");
                }
            }
            outlet(newFrame, 'b');
        };

        this.subscribers = [];
        this.gfx = new JitterObject("jit.mgraphics", this.width, this.height);
        this.gfxMatrix = new JitterMatrix('Push2', 4, "char", this.width, this.height);
    }
    return JitMgraphics;
}());


//////////////////////////////////////////
// class ColorRegustry
//////////////////////////////////////////

// ColorRegistry.js (ES5 / Max JS / V8)
// Neoplay color registry with Live palette L0..L68.
//
// Goals:
// - Register colors by name (e.g. "red", "L32")
// - Accept color inputs as:
//     1) [r,g,b,a] bytes (0..255)
//     2) [r,g,b] bytes (0..255)  -> alpha defaults to 255
//     3) "L32" (or any registered name) -> resolves to stored RGBA
// - Provide helpers for mgraphics:
//     - resolve_rgba01(input): returns [r,g,b,a] normalized 0..1
//     - set_source(mg, input): calls mg.set_source_rgba(r,g,b,a) with normalized values
//
// Notes:
// - Live provides packed 24-bit colors (0xRRGGBB) as integers.
// - We store bytes internally; convert to 0..1 on demand.

var Colors = (function ()
{
    function Colors()
    {
        // Static-only.
    }

    Colors.colors = {}; // name -> [r,g,b,a] bytes

    function clampByte(v)
    {
        v = v | 0;
        if (v < 0) { return 0; }
        if (v > 255) { return 255; }
        return v;
    }

    function isArray(x)
    {
        return Object.prototype.toString.call(x) === "[object Array]";
    }

    function toRgbaBytesFromArray(arr, defaultAlpha)
    {
        defaultAlpha = (defaultAlpha === undefined || defaultAlpha === null) ? 255 : clampByte(defaultAlpha);

        if (!arr || !arr.length)
        {
            return null;
        }

        var r = clampByte(arr[0]);
        var g = clampByte(arr[1]);
        var b = clampByte(arr[2]);
        var a = (arr.length >= 4) ? clampByte(arr[3]) : defaultAlpha;

        return [ r, g, b, a ];
    }

    function toRgbaBytesFromPackedRgbInt(packedRgb, defaultAlpha)
    {
        defaultAlpha = (defaultAlpha === undefined || defaultAlpha === null) ? 255 : clampByte(defaultAlpha);

        var v = (packedRgb >>> 0); // treat as unsigned
        // Live packed: 0xRRGGBB
        var r = (v >>> 16) & 255;
        var g = (v >>> 8) & 255;
        var b = v & 255;

        return [ r / 255, g / 255, b / 255, defaultAlpha / 255 ];
    }

    function bytesTo01(bytesRGBA)
    {
        return [
            bytesRGBA[0] / 255.0,
            bytesRGBA[1] / 255.0,
            bytesRGBA[2] / 255.0,
            bytesRGBA[3] / 255.0
        ];
    }

    // Register a color by name (bytes 0..255).
    // Examples:
    //   ColorRegistry.set_color("red", 255, 0, 0)
    //   ColorRegistry.set_color("semi", 255, 0, 0, 128)
    Colors.set_color = function (name, r, g, b, a)
    {
        if (!name)
        {
            return;
        }

        var key = String(name);
        var rgba = [
            clampByte(r),
            clampByte(g),
            clampByte(b),
            clampByte((a === undefined || a === null) ? 255 : a)
        ];

        Colors.colors[key] = rgba;
    };

    // Register many colors at once: { name: [r,g,b,a] or [r,g,b] }
    Colors.set_colors = function (map, defaultAlpha)
    {
        if (!map)
        {
            return;
        }

        var k;
        for (k in map)
        {
            if (map.hasOwnProperty(k))
            {
                var rgba = toRgbaBytesFromArray(map[k], defaultAlpha);
                if (rgba)
                {
                    Colors.colors[String(k)] = rgba;
                }
            }
        }
    };

    // Returns stored bytes [r,g,b,a] or null.
    Colors.get_color_bytes = function (name)
    {
        if (!name)
        {
            return null;
        }

        var key = String(name);
        return Colors.colors.hasOwnProperty(key) ? Colors.colors[key] : null;
    };

    // Resolve any supported input to bytes [r,g,b,a].
    // input can be:
    // - "L32" (or any registered name)
    // - [r,g,b] or [r,g,b,a] bytes
    // - number packed 0xRRGGBB
    Colors.resolve_rgba_bytes = function (input, defaultAlpha)
    {
        defaultAlpha = (defaultAlpha === undefined || defaultAlpha === null) ? 255 : clampByte(defaultAlpha);

        if (input === null || input === undefined)
        {
            return null;
        }

        if (typeof input === "string")
        {
            var c = Colors.get_color_bytes(input);
            if (!c)
            {
                return null;
            }
            return [ c[0], c[1], c[2], (c.length >= 4 ? c[3] : defaultAlpha) ];
        }

        if (isArray(input))
        {
            return toRgbaBytesFromArray(input, defaultAlpha);
        }

        if (typeof input === "number")
        {
            return toRgbaBytesFromPackedRgbInt(input, defaultAlpha);
        }

        return null;
    };

    // Resolve to normalized [r,g,b,a] in 0..1 for mgraphics
    Colors.resolve_rgba01 = function (input, defaultAlpha)
    {
        var bytes = Colors.resolve_rgba_bytes(input, defaultAlpha);
        if (!bytes)
        {
            return null;
        }
        return bytesTo01(bytes);
    };

    // Convenience for mgraphics: sets source color.
    // If alphaOverride is provided, it overrides the resolved alpha.
    Colors.set_source = function (mg, input, alphaOverride)
    {
        if (!mg || !mg.set_source_rgba)
        {
            return false;
        }

        var bytes = Colors.resolve_rgba_bytes(input, 255);
        if (!bytes)
        {
            return false;
        }

        var a = (alphaOverride === undefined || alphaOverride === null) ? bytes[3] : clampByte(alphaOverride);
        mg.set_source_rgba(bytes[0] / 255.0, bytes[1] / 255.0, bytes[2] / 255.0, a / 255.0);
        return true;
    };

    // Initialize "L0".."L68" from Live packed rgb integers.
    // packedRgbArray length should be 69 (0..68).
    Colors.init_live_colors = function (packedRgbArray, prefix)
    {
        if (!packedRgbArray || !packedRgbArray.length)
        {
            return;
        }

        var n = packedRgbArray.length;
        var i;

        for (i = 0; i < n; i++)
        {
            var rgba = toRgbaBytesFromPackedRgbInt(packedRgbArray[i], 255);
            Colors.colors[prefix + i] = rgba;
        }
    };

    Colors.init_basic_named_colors = function ()
    {
        Colors.set_color("black", 0, 0, 0, 1);
        Colors.set_color("white", 1, 1, 1, 1);
        Colors.set_color("red", 1, 0, 0, 1);
        Colors.set_color("green", 0, 1, 0, 1);
        Colors.set_color("blue", 0, 0, 1, 1);
    };

    return Colors;
}());


//////////////////////////////////////////
// class DisplayView
//////////////////////////////////////////
var DisplayView = /** @class */ (function () {
    function DisplayView(gfx, window, xStart, yStart) {
        if (xStart === void 0) { xStart = 0; }
        if (yStart === void 0) { yStart = 0; }
        var _this = this;
        this.width = 0;
        this.height = 0;
        this.matrix = null;
        this.window = window;
        this.xStart = xStart;
        this.yStart = yStart;

        // Special case: Handle 'jit_wjl_push2_lcd' window
        post("this.window.maxclass = ", this.window.maxclass, "\n");
        if (this.window.maxclass === "wjl_libusb_proxy") {
            post("Update Push2 LCD\n");
            gfx.subscribeGraphicsChanged(function (sender, gfxMatrix) {
                try {
                    _this.window.message("jit_matrix", gfxMatrix.name);
                }
                catch (err) {
                    post("ERROR: " + JSON.stringify(err, null, "    ") + "\n");
                }
            });
            return;
        }

        // Initialize dimensions
        var dstrect = this.window.getattr("dstrect");
        this.width = dstrect[2];
        this.height = dstrect[3];

        // Create JitterMatrix for cropping
        this.matrix = new JitterMatrix(4, "char", this.width, this.height);
        this.matrix.srcdimstart = [this.xStart, this.yStart];
        this.matrix.srcdimend = [this.xStart + this.width - 1, this.yStart + this.height - 1];
        this.matrix.usesrcdim = 1;

        // Subscribe to graphics updates
        gfx.subscribeGraphicsChanged(function (sender, gfxMatrix) {
            var _a, _b;
            try {
                (_a = _this.matrix) === null || _a === void 0 ? void 0 : _a.frommatrix(gfxMatrix);
                _this.window.message("jit_matrix", (_b = _this.matrix) === null || _b === void 0 ? void 0 : _b.name);
            }
            catch (err) {
                post("ERROR: " + JSON.stringify(err, null, "    ") + "\n");
            }
        });
    }

    DisplayView.classType = "DisplayView";
    return DisplayView;
}());

//////////////////////////////////////////
// function PreparedLabel()
// Function to create nice labels
//
    
//////////////////////////////////////////
// PreparedLabel.js
// Function to create nice labels
//
// Features:
// - Supports 1 or 2 lines
// - Optional tilde "~" for explicit split (only used when maxLines > 1)
// - Chooses from a small font set
// - If final line is too long: truncates either
//     a) in the middle (default), or
//     b) at the tail (when tail === true)
//
// Notes:
// - Uses an internal JitMgraphics only for measuring text widths.
//
function PreparedLabel(label, fontSize, maxWidth, maxLines, tail)
{
    // Properties for the computed label
    this.font = "";
    this.fontSize = 0;
    this.maxWidth = 0;
    this.lineCount = 0;

    this.line1 = "";
    this.line1Width = 0;

    this.line2 = "";
    this.line2Width = 0;

    // New: tail truncation mode (default false)
    this.tail = !!tail;

    this.fontSize = fontSize;
    this.maxWidth = maxWidth;

    try
    {
        this.computeLabel(label, maxLines);
    }
    catch (err)
    {
        post("ERROR PreparedLabel: ", JSON.stringify(err), "\n");
    }
}

PreparedLabel.prototype.computeLabel = function (label, maxLines)
{
    var gfx = new JitMgraphics(960, 120); // Create a new JitMgraphics object internally
    var fonts = ["arial bold", "arial narrow bold"];
    var ellipsis = "...";
    var maxWidth = this.maxWidth;

    var lastPart = null;
    var currentFont = fonts[0];

    if (!label)
    {
        this.lineCount = 0;
        return;
    }

    label = String(label);

    // ------------------------------------------------------------
    // Single-line or explicit "~" handling
    // ------------------------------------------------------------
    if (label.indexOf("~") === -1 || maxLines === 1)
    {
        // If maxLines is 1, we ignore "~" and treat as single line
        label = label.replace("~", "").trim();
        this.lineCount = 1;

        // Try fonts until it fits
        for (var fontIndex = 0; fontIndex < fonts.length; fontIndex++)
        {
            currentFont = fonts[fontIndex];
            var fullWidth = gfx.measureTextWidth(label, currentFont, this.fontSize);

            if (fullWidth <= maxWidth)
            {
                this.font = currentFont;
                this.line1 = label;
                this.line1Width = fullWidth;
                return;
            }
        }

        // Doesn't fit in either font -> needs truncation (single line)
        lastPart = label;
        currentFont = fonts[0]; // use first font for truncation attempt
        this.font = currentFont;
        this.lineCount = 1;

        var trunc1 = this._truncateWithEllipsis(lastPart, currentFont, this.fontSize, maxWidth, true /*singleLine*/);
        this.line1 = trunc1.text;
        this.line1Width = trunc1.width;
        return;
    }

    // ------------------------------------------------------------
    // Two-line allowed
    // ------------------------------------------------------------
    if (maxLines > 1)
    {
        // If "~" exists, prefer split at "~" (and no truncation unless needed)
        if (label.indexOf("~") >= 0)
        {
            var t = label.indexOf("~");
            var firstPart = label.slice(0, t).trim();
            var secondPart = label.slice(t + 1).trim();

            for (var fontIndex2 = 0; fontIndex2 < fonts.length; fontIndex2++)
            {
                currentFont = fonts[fontIndex2];
                var width1a = gfx.measureTextWidth(firstPart, currentFont, this.fontSize);
                var width2a = gfx.measureTextWidth(secondPart, currentFont, this.fontSize);

                if (width1a <= maxWidth && width2a <= maxWidth)
                {
                    this.font = currentFont;
                    this.line1 = firstPart;
                    this.line1Width = width1a;
                    this.line2 = secondPart;
                    this.line2Width = width2a;
                    this.lineCount = 2;
                    return;
                }
            }

            // "~" split exists but doesn't fit -> we will still try to do a generic best split below
        }

        // Try first font: maybe the whole thing fits single-line anyway
        currentFont = fonts[0];
        var fullWidth2 = gfx.measureTextWidth(label.replace("~", "").trim(), currentFont, this.fontSize);
        if (fullWidth2 <= maxWidth)
        {
            this.font = currentFont;
            this.lineCount = 1;
            this.line1 = label.replace("~", "").trim();
            this.line1Width = fullWidth2;
            return;
        }

        // ------------------------------------------------------------
        // Find best 2-line split (font 0)
        // ------------------------------------------------------------
        var bestSplit = null;
        var minDifference = Infinity;

        var delimiters = [" ", "-", "_", "~"];
        for (var di = 0; di < delimiters.length; di++)
        {
            var delimiter = delimiters[di];

            for (var i = 1; i < label.length; i++)
            {
                var part1 = label.slice(0, i).trim();
                var part2;

                if (label.charAt(i) === delimiter)
                {
                    part2 = label.slice(i + 1).trim();
                }
                else
                {
                    part2 = label.slice(i).trim();
                }

                // Allow split on delimiter OR camelCase/alpha-num boundaries
                var c = label.charAt(i);
                var p = label.charAt(i - 1);

                var isBoundary =
                    (label.charAt(i) === delimiter) ||
                    (c >= "A" && c <= "Z" && p >= "a" && p <= "z") ||
                    (c >= "A" && c <= "Z" && p >= "0" && p <= "9") ||
                    (c >= "a" && c <= "z" && p >= "0" && p <= "9") ||
                    (c >= "0" && c <= "9" && p >= "A" && p <= "Z") ||
                    (c >= "0" && c <= "9" && p >= "a" && p <= "z");

                if (!isBoundary)
                {
                    continue;
                }

                var w1 = gfx.measureTextWidth(part1, currentFont, this.fontSize);
                var w2 = gfx.measureTextWidth(part2, currentFont, this.fontSize);

                if (w1 <= maxWidth && w2 <= maxWidth)
                {
                    var diff = Math.abs(w1 - w2);
                    if (diff < minDifference)
                    {
                        bestSplit = { part1: part1, part2: part2, width1: w1, width2: w2 };
                        minDifference = diff;
                    }
                }
            }
        }

        if (bestSplit)
        {
            this.font = currentFont;
            this.lineCount = 2;
            this.line1 = bestSplit.part1;
            this.line1Width = bestSplit.width1;
            this.line2 = bestSplit.part2;
            this.line2Width = bestSplit.width2;
            return;
        }

        // ------------------------------------------------------------
        // If no clean split found: try second font for split
        // ------------------------------------------------------------
        currentFont = fonts[1];
        this.font = currentFont;

        var fullWidth3 = gfx.measureTextWidth(label.replace("~", "").trim(), currentFont, this.fontSize);
        if (fullWidth3 <= maxWidth)
        {
            this.lineCount = 1;
            this.line1 = label.replace("~", "").trim();
            this.line1Width = fullWidth3;
            return;
        }

        // Try to find a split even if second line might need truncation.
        // We'll pick a "longSplit" where line1 fits and is as long as possible.
        var longSplit = null;
        var longWidth = 0;

        var delimiters2 = [" ", "-", "_"];
        for (var di2 = 0; di2 < delimiters2.length; di2++)
        {
            var delimiter2 = delimiters2[di2];

            for (var j = 1; j < label.length; j++)
            {
                var a = label.slice(0, j).trim();
                var b;

                if (label.charAt(j) === delimiter2)
                {
                    b = label.slice(j + 1).trim();
                }
                else
                {
                    b = label.slice(j).trim();
                }

                var wA = gfx.measureTextWidth(a, currentFont, this.fontSize);
                if (wA <= maxWidth && wA > longWidth)
                {
                    longSplit = { part1: a, part2: b, width1: wA };
                    longWidth = wA;
                }
            }
        }

        if (longSplit)
        {
            this.lineCount = 2;
            this.line1 = longSplit.part1;
            this.line1Width = longSplit.width1;

            // line2 may be too long -> truncate line2
            lastPart = longSplit.part2;
            var trunc2 = this._truncateWithEllipsis(lastPart, currentFont, this.fontSize, maxWidth, false /*singleLine*/);

            this.line2 = trunc2.text;
            this.line2Width = trunc2.width;
            return;
        }

        // Absolute fallback: just truncate whole label into 2 lines is not meaningful here,
        // so we do single-line truncation.
        this.lineCount = 1;
        lastPart = label.replace("~", "").trim();

        var truncFallback = this._truncateWithEllipsis(lastPart, currentFont, this.fontSize, maxWidth, true /*singleLine*/);
        this.line1 = truncFallback.text;
        this.line1Width = truncFallback.width;
        return;
    }
};

// ------------------------------------------------------------
// Internal helper: truncate text to fit maxWidth using ellipsis.
//
// If this.tail === true:
//   "12 Orfeus Pluck" -> "12 Orfeus Plu..."
// else (default):
//   "12 Orfeus Pluck" -> "12 Or...Pluck"
//
PreparedLabel.prototype._truncateWithEllipsis = function (text, font, fontSize, maxWidth, singleLine)
{
    var gfx = new JitMgraphics(960, 120);
    var ellipsis = "...";

    text = (text === null || text === undefined) ? "" : String(text);

    // If even ellipsis doesn't fit, return empty/ellipsis best-effort
    var ellW = gfx.measureTextWidth(ellipsis, font, fontSize);
    if (ellW > maxWidth)
    {
        return { text: "", width: 0 };
    }

    // Tail truncation (keep start)
    if (this.tail)
    {
        // Fast path: already fits
        var wFull = gfx.measureTextWidth(text, font, fontSize);
        if (wFull <= maxWidth)
        {
            return { text: text, width: wFull };
        }

        // Binary-ish shrink from end
        var lo = 0;
        var hi = text.length;

        // We need at least 0 chars + ellipsis
        var best = ellipsis;
        var bestW = ellW;

        while (lo <= hi)
        {
            var mid = ((lo + hi) / 2) | 0;
            var candidate = text.slice(0, mid) + ellipsis;
            var w = gfx.measureTextWidth(candidate, font, fontSize);

            if (w <= maxWidth)
            {
                best = candidate;
                bestW = w;
                lo = mid + 1;
            }
            else
            {
                hi = mid - 1;
            }
        }

        return { text: best, width: bestW };
    }

    // Middle truncation (keep head + tail)
    {
        var wFull2 = gfx.measureTextWidth(text, font, fontSize);
        if (wFull2 <= maxWidth)
        {
            return { text: text, width: wFull2 };
        }

        var leftLen = Math.floor(text.length / 2);
        var rightStart = text.length - leftLen;

        var best2 = ellipsis;
        var bestW2 = ellW;

        // Expand ellipsis window until it fits
        while (leftLen >= 0 && rightStart <= text.length)
        {
            var cand = text.slice(0, leftLen) + ellipsis + text.slice(rightStart);
            var w2 = gfx.measureTextWidth(cand, font, fontSize);

            if (w2 <= maxWidth)
            {
                best2 = cand;
                bestW2 = w2;
                break;
            }

            // Reduce left and increase right (remove more from middle)
            leftLen -= 1;
            rightStart += 1;
        }

        return { text: best2, width: bestW2 };
    }
};

post('==== automation.V8.js is ready ====\n');
