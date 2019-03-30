# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import sys
import os
from xml.etree import ElementTree


class Preferences(object):
    """ 
    This class manages preferences with a cached xml file
    """
    
    def __init__(self, project):
        """
        Initializes the preference class.
        
        :param project: name of the project we're saving these prefs for
        """
        self._xml_path = None
        self._preferences = {}
        
        # Since we don't want to rely on toolkit for our source setup, instead access a
        # cached pycrypto file
        app_support = os.getenv("TWK_APP_SUPPORT_PATH")
        if ":" in app_support:
            app_support = app_support.split(":")[0]
        elif ";" in app_support:
            app_support = app_support.split(";")[0]
        self._xml_path = os.path.join(app_support, "SupportFiles", "%s_source_setup" % project)
        if not os.path.exists(self._xml_path):
            os.makedirs(self._xml_path)
        self._xml_path = os.path.join(self._xml_path, "color_prefs.xml")
        if os.path.exists(self._xml_path):
            self._read_xml_preferences()


    def retrieve(self, key):
        """
        Retrieves the key given from the stored prefs.
        
        :param key: String such as 'lut_path' that indicates what pref the script needs
        """
        return self._preferences.get(key)


    def store(self, key, value):
        """
        Save the value of the given key to the cache file.
        
        :param key: String such as 'lut_path' that indicates what pref the script wants to store
        :param value: value to be saved
        """
        # Write out a pycrypto xml file to the cache_location saving the given key/value pair
        # we only want to rewrite the creds if they are different than before
        new_preferences = {}
        if isinstance(value, unicode):
            value = value.encode("ascii", "ignore")
        if self._preferences.get(key) != value:
            new_preferences[key] = value
        if new_preferences:
            # if we have new_preferences, update the preferences dictionary and write to the prefs file
            self._preferences.update(new_preferences)
            self._write_xml_preferences(self._preferences)


    def delete(self, key):
        """
        Remove the preferences of the given key from the cache file.
        
        :param key: String such as 'lut_path' that indicates which prefs the script wants to delete
        """
        # if the key isn't in the cached data, no need to delete
        if self._preferences.get(key):
            del self._preferences[key]
            self._write_xml_preferences()


    def _read_xml_preferences(self):
        print self._xml_path
        with open(self._xml_path, "r") as xml_handle:
            tree = ElementTree.parse(xml_handle)
            for node in tree.iter():
                self._preferences[node.tag] = node.text


    def _write_xml_preferences(self, new_preferences={}):
        export_preferences = {}
        keys = self._preferences.keys()
        keys.extend(new_preferences.keys())  
        for key in keys:
            if key in new_preferences.keys():
                export_preferences[str(key)] = new_preferences.get(key)
            else:
                export_preferences[str(key)] = self._preferences.get(key)
        with open(self._xml_path, "w") as xml_handle:
            root = ElementTree.Element("root")
            for key, val in export_preferences.iteritems():
                ElementTree.SubElement(root, key).text = val
            tree = ElementTree.ElementTree(root)
            tree.write(xml_handle)
