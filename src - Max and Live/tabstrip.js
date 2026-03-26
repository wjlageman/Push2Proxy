post('==== Compiling JS tabstrip starts\n');

// Max JavaScript code to manage tab visibility based on patcher state

inlets = 1;
outlets = 1;

var tabInfos = []; // Array of objects { name: 'TabName', index: 1, obj: object }
var thispatcher = this.patcher;
var last_edit_state = null;
var last_presentation_state = null;
var checkTask = null;
var selectedTabIndex = 0;
var initialized = false;

function loadbang()
{
    if (initialized) {
        // Prevent reinitialization if already initialized
        return;
    }
    initialized = true;

    updateTabNames();
    updateTabVisibility();

    // Initialize the last known states
    last_edit_state = thispatcher.locked;
    last_presentation_state = thispatcher.getattr("presentation");

    // Set up a Task to periodically check the edit and presentation states
    checkTask = new Task(checkPatcherState, this);
    checkTask.interval = 500; // Check every 500 milliseconds
    checkTask.repeat();
}

function checkPatcherState()
{
    if (thispatcher == null)
    {
        // If the parent patcher is not available, stop the task
        if (checkTask) checkTask.cancel();
        return;
    }

    var current_edit_state = thispatcher.locked;
    var current_presentation_state = thispatcher.getattr("presentation");

    // Check if the edit state or presentation mode has changed
    if (current_edit_state !== last_edit_state || current_presentation_state !== last_presentation_state)
    {
        last_edit_state = current_edit_state;
        last_presentation_state = current_presentation_state;
        updateTabVisibility();
    }
}

function notifydeleted()
{
    // Clean up the Task when the object is deleted
    if (checkTask)
    {
        checkTask.cancel();
        checkTask = null;
    }
}

function updateTabNames()
{
    //post('Updating tab names\n');

    if (thispatcher == null)
    {
        post("Error: Thispatcher not found.\n");
        return;
    }

    // Find all bpatchers with a scripting name
    tabInfos = []; // Clear the tabInfos array

    thispatcher.apply(
        function(b)
        {
            if (b.maxclass === 'patcher')
            {
                var scripting_name = b.varname;
                if (scripting_name && scripting_name.length > 0)
                {
                    // Parse the varname to extract the base name and index
                    var match = scripting_name.match(/^(.+)\[(\d+)\]$/);
                    if (match)
                    {
                        var baseName = match[1];
                        var index = parseInt(match[2], 10);
						//post('name:', baseName, 'index:', index, 'obj:', b , '\n');
                        tabInfos.push({ name: baseName, index: index, obj: b });
                    }
                    else
                    {
                        post("Warning: Bpatcher varname '" + scripting_name + "' does not match expected pattern 'Name[Index]'.\n");
                    }
                }
            }
            return true; // Continue iteration
        }
    );

    if (tabInfos.length === 0)
    {
        post("Error: No bpatchers with valid scripting names found in parent patcher.\n");
        return;
    }

    // Sort tabInfos based on index
    tabInfos.sort(function(a, b) { return a.index - b.index; });

    // Get the tab names
    var tabnames = tabInfos.map(function(info) { return info.name; });

    // Get the tabstrip object
    var tabstrip = thispatcher.getnamed("tabstrip");
    if (tabstrip == null)
    {
        post("Error: 'tabstrip' object not found in parent patcher.\n");
        return;
    }

    // Set the 'tabs' attribute of the tabstrip object
    tabstrip.message("tabs", tabnames);

    // Only set the tabstrip's value if it's not already set
    if (tabstrip.getvalueof() !== selectedTabIndex)
    {
        tabstrip.message("set", selectedTabIndex);
    }

    //post("Tab names updated: ", tabnames.join(", "), "\n");
}

function updateTabVisibility()
{
    if (thispatcher == null)
    {
        post("Error: Parent patcher not found.\n");
        return;
    }

    var is_editing = !thispatcher.locked;
    var is_presentation = thispatcher.getattr("presentation");

    if (is_editing)
    {
        // Edit Mode: Show all bpatchers for editing
        for (var i = 0; i < tabInfos.length; i++)
        {
            var tabobj = tabInfos[i].obj;
            if (tabobj != null && tabobj.hidden)
            {
                tabobj.hidden = false;
                //post("Showing tab (edit mode): ", tabInfos[i].name, "\n");
            }
        }
    }
    else
    {
        // Performance Mode
        if (is_presentation)
        {
            // Presentation Mode: Use tabstrip to control visibility
            //post("Presentation Mode: Using tabstrip for visibility control.\n");
            // Ensure the selectedTabIndex is valid
            if (selectedTabIndex < 0 || selectedTabIndex >= tabInfos.length)
            {
                selectedTabIndex = 0;
            }
            selecttab(selectedTabIndex);
        }
        else
        {
            // Patcher Mode: Show all bpatchers
            for (var i = 0; i < tabInfos.length; i++)
            {
                var tabobj = tabInfos[i].obj;
                if (tabobj != null && tabobj.hidden)
                {
                    tabobj.hidden = false;
                    //post("Showing tab (patcher mode): ", tabInfos[i].name, "\n");
                }
            }
        }
    }
}

function selecttab(tabnumber)
{
    if (tabInfos.length === 0)
    {
        updateTabNames();
    }

    if (tabnumber < 0 || tabnumber >= tabInfos.length)
    {
        post("Error: Tab number out of range.\n");
        return;
    }

    if (thispatcher == null)
    {
        post("Error: Parent patcher not found.\n");
        return;
    }

    selectedTabIndex = tabnumber;
    outlet(0, tabnumber)
	messnamed("js_port", "active_tab", tabnumber);
	

    // Get the tabstrip object
    var tabstrip = thispatcher.getnamed("tabstrip");
    if (tabstrip == null)
    {
        post("Error: 'tabstrip' object not found in parent patcher.\n");
        return;
    }
    // Only set the tabstrip's value if it's not already set
    if (tabstrip.getvalueof() !== tabnumber)
    {
        tabstrip.message("set", tabnumber);
    }

    for (var i = 0; i < tabInfos.length; i++)
    {
        var tabobj = tabInfos[i].obj;
        if (tabobj != null)
        {
            if (i === tabnumber)
            {
                if (tabobj.hidden)
                {
                    // Show the selected tab
                    tabobj.hidden = false;
                    //post("Showing tab: ", tabInfos[i].name, "\n");
                }
            }
            else
            {
                if (!tabobj.hidden)
                {
                    // Hide other tabs
                    tabobj.hidden = true;
                }
            }
        }
        else
        {
            post("Error: Tab object '", tabInfos[i].name, "' not found in parent patcher.\n");
        }
    }
}

post('==== Compiling JS tabstrip ends\n');

// Start this code
loadbang()
