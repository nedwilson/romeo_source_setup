# Copyright (c) 2017 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import sys
import glob
import os
import re
import logging
import xml.dom.minidom
import ConfigParser

from rv import rvtypes, rvui, commands, extra_commands, runtime

from preferences import Preferences


def group_member_of_type(node, member_type):
    """
    Checks a node group for a node of a specific type.
    
    :param node: name of node type to find
    :param member_type: node group to search
    """
    for n in commands.nodesInGroup(node):
        if commands.nodeType(n) == member_type:
            return n
    return None


class RomeoSourceSetup(rvtypes.MinorMode):
    """
    Configures custom RV settings for Level Up for mattes, CDLs, linearization, and luts.
    
    See ticket # for full description.
    """

    def __init__(self):
        rvtypes.MinorMode.__init__(self)

        self._look_lut_path = None
        # Since we want the matte to stay on for all frames regardless of file type, we manage
        # the matte state with a global variable
        # since we're doing the slate management as a custom thing, we need to store whether
        # the slate is currently on or off, but at the beginning we assume that the slate is on
        self._slate_on = True
        self._handles_on = True

        self.init("Romeo Source Setup", None,
                  [("after-session-read", self._set_display_to_no_correction, ""),
                   ("source-group-complete", self.source_setup_romeo, "Color Management"),
                   ("key-down--f6", self.toggle_wipes, "Over Mode and Wipes on/off")],
                  [("Color", [("Romeo Shot LUT", self.toggle_look, "alt meta l", self.look_menu_state)])],
                  # defines custom menu item for matte
                  "source_setup", 1)  # 1 will put this after the default "source_setup"

        self._logger = logging.getLogger()
        self._logger.addHandler(logging.StreamHandler())
        self._logger.setLevel(logging.INFO)
        self._show_cfg = ConfigParser.ConfigParser()
        self._show_cfg.read(self._retrieve_cfg_path())
        self._shot_regexp = re.compile(self._show_cfg.get(self._show_code, 'shot_regexp'))
        self._mainplate_regexp = re.compile(self._show_cfg.get(self._show_code, 'mainplate_regexp'))
        self._shot_color_dir = self._show_cfg.get(self._show_code, 'cdl_dir_format').format(pathsep = os.path.sep)

        # since alt-f is already bound in presentation_mode, we need to unbind it first before ours will work
        commands.unbind("presentation_control", "global", "key-down--alt--f")

        # bind other hotkeys
        commands.bind("default", "global", "key-down--alt--f", self.toggle_media, "Swap Shotgun Format Media")
        commands.bind("default", "global", "key-down--alt--s", self.toggle_slate, "Slate on/off")
        commands.bind("default", "global", "key-down--alt--h", self.toggle_handles, "Handles on/off")

    def source_setup_romeo(self, event, noColorChanges=False):
        """
        Finds all the RV nodes we need to operate on, and does the bulk of the color setup
        dependant on file type.  Also handles finding the default file paths for luts and
        CDLs and storing them in a preferences file so they only have to be picked once.
        
        :param event: event passed in from RV
        :param noColorChanges: 
        """
        #  event.reject() is done to allow other functions bound to
        #  this event to get a chance to modify the state as well. If
        #  its not rejected, the event will be eaten and no other call
        #  backs will occur.

        event.reject()
        
        args             = event.contents().split(";;")
        group            = args[0]
        action           = args[-1]
        file_source      = group_member_of_type(group, "RVFileSource")
        image_source     = group_member_of_type(group, "RVImageSource")
        source           = file_source if image_source == None else image_source
        lin_pipe_node    = group_member_of_type(group, "RVLinearizePipelineGroup")
        lin_node         = group_member_of_type(lin_pipe_node, "RVLinearize")
        look_pipe_node   = group_member_of_type(group, "RVLookPipelineGroup") 
        file_names       = commands.getStringProperty("%s.media.movie" % source)
        
        # make sure our Display is forced to "No Correction"
        self._set_display_to_no_correction(event)
        
        # Modify the Look Pipeline to account for both EXR and QT handling. We put the
        # EXR nodes in the QT pipe and vice versa because there are menu items that depend
        # on the nodes existing that will throw errors if they don't exist.  So we just
        # manage which nodes are active for the particular source types rather than
        # keeping them out of the pipe.
        commands.setStringProperty(
            "%s.pipeline.nodes" % look_pipe_node, 
            ["LinearToAlexaLogC", "RVLookLUT", "LinearToRec709"],
            True
        )
        alexa_node = group_member_of_type(look_pipe_node, "LinearToAlexaLogC")
        look_node = group_member_of_type(look_pipe_node, "RVLookLUT")
        rec709_node = group_member_of_type(look_pipe_node, "LinearToRec709")
        
        for file_name in file_names:
            # if the file is an exr or dpx, handle it accordingly,
            # anything else we don't need to monkey with aside from
            # making sure we force it to sRGB to account for
            # "No Correction" in the display profile
            if os.path.splitext(file_name)[-1].lower() in [".exr", ".dpx"]:
                # check prefs to see if there's a saved directory to 
                # look for shot cdls
                if not self._look_lut_path:
                    self._look_lut_path = self._retrieve_csp_path(file_name)

                # now disable our LinearToSRGB node since that's only
                # in the pipeline for non-EXR files
                commands.setIntProperty("%s.node.active" % rec709_node, [0], True)
                self.do_exr_linearization(lin_node)
                self.do_exr_look_setup(look_node)
            else:
                # if we're not dealing with an EXR just make sure we
                # convert to sRGB to account for the forced display
                # profile
                commands.setIntProperty("%s.node.active" % alexa_node, [0], True)
                commands.setIntProperty("%s.lut.active" % look_node, [0], True)
                commands.setIntProperty("%s.node.active" % rec709_node, [0], True)
                
    def _set_display_to_no_correction(self, event):
        """
        Makes sure we have No Correction set in the View menu by
        disabling sRGB and Rec709 for all DisplayColor nodes.
        
        This is less confusing for users than setting up a display
        profile, so we do this here.
        """
        display_nodes = commands.nodesOfType("RVDisplayColor")
        for display_node in display_nodes:
            commands.setIntProperty("%s.color.sRGB" % display_node, [0], True)
            commands.setIntProperty("%s.color.Rec709" % display_node, [0], True)
                
    def _retrieve_cfg_path(self):
        """
        Obtains a saved path from Preferences or asks the user which
        path should be used and saves it for future use.
        """
        prefs = Preferences("romeo")
        show_cfg_file = prefs.retrieve("show_cfg_file")
        while not show_cfg_file:
            try:
                show_cfg_file = os.environ['IH_SHOW_CFG_PATH']
            except KeyError:
                self._logger.warning('Environment variable IH_SHOW_CFG_PATH is not defined.')
            # if there's not a file path set for the file lut,
            # pop up a dialog to ask for one
            show_cfg_file = commands.openFileDialog(False, False, False, '*', '/Volumes/romeo_inhouse/romeo/SHARED/romeo/lib/')
            if show_cfg_file and not os.path.exists(show_cfg_file[0]):
                # if we can't see the path, reset the path so
                # that we can ask for it again
                self._logger.warning("Chosen Romeo config file does not exist on disk, choose again.")
                show_cfg_file = None
            else:
                # otherwise store the preference so we don't
                # have to find the path again next time
                prefs.store("show_cfg_file", show_cfg_file[0])
                shot_cdl_path = show_cfg_file[0]
        show_code = prefs.retrieve("show_code")
        while not show_code:
            # get the show code if it exists in the environment
            try:
                show_code = os.environ['IH_SHOW_CODE']
            except KeyError:
                self._logger.warning('Environment variable IH_SHOW_CODE is not defined. Hard-coding to romeo...')
                show_code = 'romeo'
            prefs.store("show_code", show_code)
        self._show_code = show_code
        return show_cfg_file
    
    def _retrieve_csp_path(self, file_name):
        """
        Checks the file system for a shot cdl, raises warnings if not
        found.
        
        :param str file_name: path of file being currently examined
        """
        # if we don't have a shot name, no need to set up a cdl
        if not file_name:
            self._logger.warning("Method argument file_name is set to None.")
            return
        if not os.path.exists(os.path.dirname(file_name)):
            self._logger.warning("Not sure how this happened, but looks like we were called with a file_name parameter that doesn't exist.")
            self._logger.warning("Unable to find %s on filesystem."%file_name)
            return

        # now that we have a valid filename, let's split up the path.
        path_array = file_name.split(os.path.sep)
        shot_root_dir_array = []
        for path_element in path_array:
            shot_root_dir_array.append(path_element)
            if self._shot_regexp.search(path_element):
                break
        shot_root_dir = os.path.sep.join(shot_root_dir_array)
        self._logger.info('Shot root directory: %s'%shot_root_dir)
        shot_color_dir = os.path.join(shot_root_dir, self._shot_color_dir)
        self._logger.info('Shot color directory: %s'%shot_color_dir)
        if not os.path.exists(shot_color_dir):
            self._logger.warning('Shot color directory %s does not exist.'%shot_color_dir)
            return
        if not os.path.isdir(shot_color_dir):
            self._logger.warning('Shot color directory %s is not a directory.'%shot_color_dir)
            return


        # check to see if there's a shot CDL file that can be applied by looking
        # for a parent directory named after the shot and checking for a cc file
        cc_files = glob.glob(os.path.join(shot_color_dir, '*'))
        csp_files = []
        cube_files = []
        for file_name in cc_files:
            if os.path.splitext(file_name)[-1].lower() == '.cube':
                cube_files.append(file_name)
            elif os.path.splitext(file_name)[-1].lower() == '.csp':
                csp_files.append(file_name)
                    
        # if we didn't find a cdl file, warn the user and disable the node
        if len(csp_files) == 0 and len(cube_files) == 0:
            self._logger.warning("No CC files found in: %s, disabling per shot LUT" % shot_color_dir)
            return
        
        # on the off chance there's more than one cdl sort by modified time so we use
        # the latest
        csp_files.sort(key=lambda x: os.stat(x).st_mtime, reverse=True)
        cube_files.sort(key=lambda x: os.stat(x).st_mtime, reverse=True)
        likely_lut = None
        for csp_file in csp_files:
            if self._mainplate_regexp.search(csp_file):
                likely_lut = csp_file
                break
        if not likely_lut and len(csp_files) > 0:
            likely_lut = csp_files[0]

        if not likely_lut:
            for cube_file in cube_files:
                if self._mainplate_regexp.search(cube_file):
                    likely_lut = cube_file
                    break
        if not likely_lut and len(cube_files) > 0:
            likely_lut = cube_files[0]

        self._logger.info('Likely LUT file: %s'%likely_lut)
        return likely_lut
    
    def _get_node_for_source(self, node_type):
        """
        Finds the node of the given type for the currently viewed
        source.
        
        :param str node_type: RV node type, eg. RVColor, RVCDL
        """
        # first find the source for the frame we're currently viewing
        frame = commands.frame()
        # file_source = None
        for source in extra_commands.nodesInEvalPath(frame, "RVFileSource", None):
            file_source = source
            continue

        source_group = commands.nodeGroup(file_source)
        
        # now find the node of the given type for that source
        pipe_node  = group_member_of_type(source_group, "RVLookPipelineGroup")
        return group_member_of_type(pipe_node, node_type)

    ###################
    #
    # EXR
    #
    ###################

    def do_exr_linearization(self, lin_node):
        """
        Makes sure the linearization setting is turned OFF.  In order
        to make sure that happens correctly, we need to set more than
        just the logtype setting, unfortunately, as header settings can
        turn it back on otherwise.  Setting logtype and sRGB2linear, 
        should be sufficient for all edge cases.
        
        :param lin_node: RVLinearize node for the source
        """
        self._logger.info("Set linearize node to 'No Linearization'")
        commands.setIntProperty("%s.color.logtype" % lin_node, [0], True)
        commands.setIntProperty("%s.color.sRGB2linear" % lin_node, [0], True)

    def do_exr_look_setup(self, look_node):
        """
        Takes the shot-specific csp (or cube) file that was previously located and applies it.
        
        :param look_node: RVLookLUT node
        """
        look_path = self._look_lut_path
        # if the file isn't bundled with the RV package, we can't do anything, so exit
        if not os.path.exists(look_path):
            self._logger.warning("Look LUT not found at: %s" % look_path)
            return
        commands.readLUT(look_path, look_node)
        commands.setIntProperty("%s.lut.active" % look_node, [1], True)
        commands.updateLUT()
        self._logger.info("Loaded Look LUT: %s" % look_path)
        
    def toggle_look(self, event):
        """
        If the LookLUT is currently on, turn it off, and vice versa.
        Display feedback so the user knows what's happening.
        """
        # since the CDL should be enabled or disabled for a single
        # source rather than on the session as a whole, reference the
        # currently viewed node to toggle
        look_node = self._get_node_for_source("RVLookLUT")

        look_on = commands.getIntProperty("%s.lut.active" % look_node)[0]
        if look_on:
            commands.setIntProperty("%s.lut.active" % look_node, [0], True)
            extra_commands.displayFeedback("Romeo Shot LUT is OFF", 5.0)
        else:
            commands.setIntProperty("%s.lut.active" % look_node, [1], True)
            extra_commands.displayFeedback("Romeo Shot LUT is ON", 5.0)

    def look_menu_state(self):
        """
        Returns the menu state of the Technicolor LUT menu item.
        """
        # since the CDL should be enabled or disabled for a single
        # source rather than on the session as a whole, reference the
        # currently viewed node to toggle
        look_node = self._get_node_for_source("RVLookLUT")
        
        look_on = commands.getIntProperty("%s.lut.active" % look_node)[0]
        if look_on:
            return commands.CheckedMenuState
        return commands.UncheckedMenuState
    
    #########################
    #
    # Hotkey support
    #
    #########################
    
    def toggle_wipes(self, var):
        """
        If there is multiple media sources, then toggle both over mode and wipes on/off, otherwise
        default back to standard wipe toggling behavior.
        """
        if len(commands.sources()) > 1:
            wipe_shown = runtime.eval("rvui.wipeShown();", ["rvui"])
            wipe_shown = int(str(wipe_shown))
            # if Wipes are on, turn them off and vice versa
            if wipe_shown == commands.CheckedMenuState:
                # turn wipes off
                runtime.eval("rvui.toggleWipe();", ["rvui"])
                # make sure we're in "Sequence" mode
                commands.setViewNode("defaultSequence")
                extra_commands.displayFeedback("Wipes OFF", 5.0)
            else:
                # make sure we're in "Over" mode
                commands.setViewNode("defaultStack")
                # turn wipes on
                runtime.eval("rvui.toggleWipe();", ["rvui"])
                extra_commands.displayFeedback("Wipes ON", 5.0)
        else:
            extra_commands.displayFeedback("Can't wipe, only one source", 5.0)
            
    def toggle_media(self, var):
        """
        Swap between Shotgun format media (frames/movie). Also
        handles the case where we're not looking at Shotgun media, by
        bailing out gracefully.
        """
        source_node = commands.closestNodesOfType("RVFileSource")[0]
        try:
            media_type = commands.getStringProperty("%s.tracking.mediaType" % source_node)[0]
        except:
            # if the previous command throws an exception, we aren't
            # looking at Shotgun sources
            pass
        else:
            mu = """
                require shotgun_mode;
                shotgun_mode.theMode().swapMediaFromInfo("%s", "%s");
            """
            if str(media_type.lower()) == "dnxhd":
                runtime.eval(mu % ("Frames", source_node), ["shotgun_mode"])
            else:
                runtime.eval(mu % ("DNXHD", source_node), ["shotgun_mode"])
                
            # recheck our current media_type since it's possible the
            # media type doesn't exist and therefore wouldn't have
            # changed
            media_type = commands.getStringProperty("%s.tracking.mediaType" % source_node)[0]
            if str(media_type).lower() == "frames":
                # make sure our alexa node is active
                commands.setIntProperty("#LinearToAlexaLogC.node.active", [1], True)
            else:
                # make sure our alexa node is not active
                commands.setIntProperty("#LinearToAlexaLogC.node.active", [0], True)
            # and display some feedback so the user knows what's happening
            extra_commands.displayFeedback("View %s" % media_type.upper(), 5.0)
            
                
    def toggle_slate(self, var):
        """
        If the slate is "on", lop off the first frame, otherwise, add it back in
        """
        source_nodes = commands.closestNodesOfType("RVFileSource")
        for source_node in source_nodes:
            source_path = commands.getStringProperty("%s.media.movie" % source_node)[0]
            start_frame = 0
            for source in commands.sources():
                if source[0] == source_path:
                    start_frame = int(source[1])
                    break
            if self._slate_on:
                commands.setIntProperty("%s.cut.in" % source_node, [start_frame + 1], True)
            else:
                commands.setIntProperty("%s.cut.in" % source_node, [start_frame], True)      
        # we only want to set the flag and display feedback once, not for each source
        if self._slate_on:
            extra_commands.displayFeedback("Slate is OFF", 5.0)
            self._slate_on = False
        else:
            extra_commands.displayFeedback("Slate is ON", 5.0)
            self._slate_on = True

    def toggle_handles(self, var):
        """
        If the handles are "on", lop off 8 at the head and tail, else, add them back in
        """
        source_nodes = commands.closestNodesOfType("RVFileSource")
        for source_node in source_nodes:
            source_path = commands.getStringProperty("%s.media.movie" % source_node)[0]
            start_frame = 0
            end_frame = -1
            for source in commands.sources():
                if source[0] == source_path:
                    start_frame = int(source[1])
                    end_frame = int(source[2])
                    break
            if self._handles_on:
                commands.setIntProperty("%s.cut.in" % source_node, [start_frame + 9], True)
                commands.setIntProperty("%s.cut.out" % source_node, [end_frame - 8], True)
            else:
                commands.setIntProperty("%s.cut.in" % source_node, [start_frame], True)
                commands.setIntProperty("%s.cut.out" % source_node, [end_frame], True)

        # we only want to set the flag and display feedback once, not for each source
        if self._handles_on:
            extra_commands.displayFeedback("Handles are OFF", 5.0)
            self._handles_on = False
        else:
            extra_commands.displayFeedback("Handles are ON", 5.0)
            self._handles_on = True


def createMode():
    print("Loading ROMEO source_setup...")
    return RomeoSourceSetup()
