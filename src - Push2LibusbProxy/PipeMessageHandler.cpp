#include "FrameHandler.h"
#include "LibusbProxy.h"
#include "Debug.h"

// This function simulates processing of an incoming message.
bool ProcessPipeMessage(const char* inMessage, char* replyBuffer, size_t messageSize, size_t* replySize)
{
    pipe_data_transfer* pd = (pipe_data_transfer*)inMessage;
    DEBUG_LOG("In ProcessPipeMessage Type: %s, Message: %s", pd->type, pd->message);

    // Check if it is a blend command
    if (strncmp(pd->type, "COMMAND", 7) == 0 && strncmp(pd->message, "Blend", 5) == 0)
    {
        pipe_blend_command* pdc = (pipe_blend_command*)inMessage;
        DEBUG_LOG("Blend xPos %d, yPos %d, width %d, height %d, liveBlend %d, maxBlend %d", pdc->xPos, pdc->yPos, pdc->width, pdc->height, pdc->liveBlend, pdc->maxBlend);
        time_log("start");
        for (int y = pdc->yPos; y < pdc->yPos + pdc->height; y++)
        {
            for (int x = pdc->xPos; x < pdc->xPos + pdc->width; x++)
            {
                blendPixels->at(x, y).live = pdc->liveBlend;
                blendPixels->at(x, y).max = pdc->maxBlend;
            }
        }
        time_log("");

        // Show the result
        process_frame_max();
        return true;
    }

    // GetLine from Live frame: COMMAND asking for a line from a Live frame
    if (strncmp(pd->type, "COMMAND", 7) == 0 && strncmp(pd->message, "GetLine", 7) == 0)
    {
        pipe_get_live_frame_line_command* cmd = (pipe_get_live_frame_line_command*)inMessage;
        const int line = cmd->line;
        DEBUG_LOG("GET LINE OF LIVE FRAME %d", line);

        pipe_data_transfer* pdt = (pipe_data_transfer*)replyBuffer;
        memset(pdt, 0, sizeof(pipe_data_transfer));
        sprintf(pdt->type, "DATA");
        sprintf(pdt->message, "LiveDataLine");
        pdt->lineNr = (BYTE)line;
        const RGB* src = livePixels->getData() + line * 960;
        memcpy(pdt->pixels, src, 960 * sizeof(RGB));
        *replySize = (size_t)sizeof(pipe_data_transfer);

        return true;
    }

    // Get a Live frame: COMMAND asking for a whole Live frame
    if (strncmp(pd->type, "COMMAND", 7) == 0 && strncmp(pd->message, "GetFrame", 8) == 0)
    {
        DEBUG_LOG("FOUND GETFRAME 1");
        //pipe_get_frame_command* cmd = (pipe_get_frame_command*)inMessage;

        pipe_frame_transfer* pft = (pipe_frame_transfer*)replyBuffer;
        DEBUG_LOG("FOUND GETFRAME 2 sizeof(pipe_frame_transfer) %d, replysize %d", sizeof(pipe_frame_transfer), *replySize);
        memset(pft, 0, sizeof(pft));
        DEBUG_LOG("GETFRAME 2a memset done");
        sprintf(pft->type, "DATA");
        DEBUG_LOG("GETFRAME 3 \"DATA\" %s", pft->type);
        sprintf(pft->message, "LiveFrame");
        DEBUG_LOG("GETFRAME 4 \"LiveFrame\" %s", pft->message);
        const RGB* src = livePixels->getData();
        DEBUG_LOG("GETFRAME 5 %p PixelSize: %d, capacity %d", src, 960 * 160 * sizeof(RGB), messageSize);
        memcpy(pft->pixels, src, 960 * 160 * sizeof(RGB));
        DEBUG_LOG("GETFRAME 6 Size: %d", 960 * 160 * sizeof(RGB));
        *replySize = (size_t)sizeof(pipe_frame_transfer);
        DEBUG_LOG("GETFRAME 7 replysize %ld", *replySize);

        return true;
    }

    // Heartbeat: one-way COMMAND/Heartbeat (no reply)
    // Assuming your packet is a struct with pd->type and pd->message (as you indicated):
    if (strncmp(pd->type, "COMMAND", 7) == 0 && strncmp(pd->message, "Heartbeat", 9) == 0)
    {
        DEBUG_LOG("KEEP_MAX_ALIVE");
        TouchMaxKeepalive(KEEP_MAX_ALIVE_TIMEOUT); // extend to 2000 ms by default from now, defined in FrameHandler.h
        return true;             // handled, no reply
    }

    // Check that the type is "DATA"
    if (strncmp(pd->type, "DATA", 4) != 0 || strncmp(pd->message, "MaxDataLine", 11) != 0 || pd->lineNr < 0 || pd->lineNr > 159)
    {
        DEBUG_LOG("ERROR: in MaxData line %d", pd->lineNr);
        return false;
    }
    // Copy the 960 RGB pixels from the message into the appropriate row in the maxPixels matrix.
    // Each row is 960 pixels long.
    RGB* dest = maxPixels->getData();
    memcpy(dest + pd->lineNr * 960, pd->pixels, 960 * sizeof(RGB));

    if (pd->lineNr == 159)
    {
        process_frame_max();
        TouchMaxKeepalive(KEEP_MAX_ALIVE_TIMEOUT); // extend to 2000 ms by default from now, defined in FrameHandler.h
    }

    /*
    // Polling will be needed to signal incoming Live frames to MaxForLive
    // it is not implemented yet
    if (strncmp(pd->type, "POLLING", 7) == 0 && strncmp(pd->message, "News?", 5) == 0)
    {
        pipe_message_transfer* pollMsg = (pipe_message_transfer*) replyBuffer;
        *replySize = sizeof(pipe_message_transfer);
        memset(pollMsg, 0, sizeof(pipe_message_transfer));
        strcpy(pollMsg->type, "POLLING");
        if (newLiveFrame)
        {
            strcpy(pollMsg->message, "New Live frame");
            newLiveFrame = false; // Set here se the new frame is only reported once.
        }
        else
        {
            strcpy(pollMsg->message, "No news");
        }
    }
    */
    return true;
}
