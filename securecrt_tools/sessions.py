"""
This module includes a collection of "session" objects that represent a session to a remote device.  To some degree, a
session object can be thought of as a tab in SecureCRT, since you can disconnect from a device and then connect to
others with the same session object.    These classes are intended as a wrapper around the SecureCRT Python API to
simplify common tasks that are performed against network devices such as routers and switches.  As with the Script
class, there is also a DebugSession class as a part of this module to allow running the code by the local python
interpreter so that the scripts can be debugged.

The base class is named "Session" is the parent for more specific session types and includes all methods that must be
implemented by all sub-classes.

The primary subclass is called "CRTSession" which is specific to interacting with the Python API for SecureCRT.
Whenever a script is launched from SecureCRT, this class should be used to interact with SecureCRT.

A second subclass called "DebugSession" is used to run scripts outside of SecureCRT, such as in an IDE.  This is useful
for debugging because you can run your script along with the IDE debugging tools while simulating the interactions with
SecureCRT.  The class has the same API as CRTSession so that no modifications are needed to run a script directly.  For
example, while a CRTSession may directly pull input from a device before processing it, if the script is launched from
an IDE, the DebugSession object will instead prompt for a filename containing the same output that would be been
received from the remote device.  The script can then be debugged step-by-step to help the programmer better understand
where their logic is having trouble with a particular output.

"""

import os
import sys
import logging
import time
import re
from abc import ABCMeta, abstractmethod
from message_box_const import *

# ################################################    EXCEPTIONS     ###################################################


class ConnectError(Exception):
    """
    An exception type that is raised when there are problems connecting to a device.
    """
    pass


class InteractionError(Exception):
    """
    An exception type used when an expected response isn't received when interacting with a device.
    """
    pass


class UnsupportedOSError(Exception):
    """
    An exception type used when the remote device is running an OS that isn't supported by the script.
    """
    pass


# ##############################################    SESSION TYPES     ##################################################


class Session:
    """
    This is a base class for the other Session types.  This class simply exists to enforce the required methods any
    sub-classes have to implement.  There are also a couple methods that are common to all sessions so they are defined
    under this class and automatically inherited by the sub-classes.
    """
    __metaclass__ = ABCMeta

    def __init__(self):
        self.script = None
        self.os = None
        self.prompt = None
        self.prompt_stack = []
        self.hostname = None
        self.term_len = None
        self.term_width = None
        self.logger = logging.getLogger("securecrt")

    def create_output_filename(self, desc, ext=".txt", include_hostname=True, include_date=True, base_dir=None):
        """
        Generates a filename (including absoluate path) based on details from the session.

        :param desc: A short description to include in the filename (i.e. "show run", "cdp", etc)
        :type desc: str
        :param base_dir: (Optional) The director where this file should be saved. Default: SavePath from settings.
        :type base_dir: str
        :param ext: (Optional) Extension for the filename.  Default: ".txt"
        :type ext: str
        :param include_date: (Optional) Include a timestamp in the filename.  The timestamp format is taken from the
            settings file.  Default: True
        :type include_date: bool

        :return: The generated absolute path for the filename requested.
        :rtype: str
        """

        self.logger.debug("<CREATE_FILENAME> Starting creation of filename with Desc: {0}, Base Dir: {1}, ext: {2}, "
                          "include_date: {3}".format(desc, base_dir, ext, include_date))

        if base_dir:
            save_path = os.path.realpath(base_dir)
        else:
            save_path = self.script.output_dir

        self.logger.debug("<CREATE_FILENAME> Save Location: {0}".format(save_path))

        # Remove reserved filename characters from filename
        clean_desc = desc.replace("/", "-")
        clean_desc = clean_desc.replace(".", "-")
        clean_desc = clean_desc.replace(":", "-")
        clean_desc = clean_desc.replace("\\", "")
        clean_desc = clean_desc.replace("| ", "")
        # Just in case the trailing space from the above replacement was missing.
        clean_desc = clean_desc.replace("|", "")

        if include_hostname:
            self.logger.debug("<CREATE_FILENAME> Using hostname.")
            hostname = self.hostname
        else:
            self.logger.debug("<CREATE_FILENAME> NOT using hostname.")
            hostname = ""

        if include_date:
            # Get the current date in the format supplied in date_format
            my_date = self.script.datetime
        else:
            self.logger.debug("<CREATE_FILENAME> Not including date.")
            my_date = ""

        file_bits = [hostname, clean_desc, my_date]
        self.logger.debug("<CREATE_FILENAME> Using {0} to create filename".format(file_bits))
        # Create filename, stripping off leading or trailing "-" if some fields are not used.
        filename = '-'.join(file_bits).strip("-")
        # If ext starts with a '.', add it, otherwise put the '.' in there ourselves.
        if ext[0] == '.':
            filename = filename + ext
        else:
            filename = "{0}.{1}".format(filename, ext)
        file_path = os.path.join(save_path, filename)
        self.logger.debug("<CREATE_FILENAME> Final Filename: {0}".format(file_path))

        return file_path

    def validate_os(self, valid_os_list):
        """
        This method checks if the remote device is running an OS in a list of valid OSes passed into the method.  If
        the OS is not in the list then an exception is raised, which can either be allowed to cause the script to exit
        or be caught in a "try, except" statement and allow the script to take another action based on the result.  If
        the remote OS is in the valid list, then nothing happens.

        :param valid_os_list: A list of OSs that
        """
        if self.os not in valid_os_list:
            self.logger.debug("Unsupported OS: {0} not in {1}.  Raising exception.".format(self.os, valid_os_list))
            raise UnsupportedOSError("Remote device running unsupported OS: {0}.".format(self.os))

    @abstractmethod
    def is_connected(self):
        """
        Returns a boolean value that describes if the session is currently connected.

        :return: True if the session is connected, False if not.
        :rtype: bool
        """
        pass

    @abstractmethod
    def connect_ssh(self, host, username, password, prompt_endings=("#", ">")):
        """
        Connects to a device via the SSH protocol. By default, SSH2 will be tried first, but if it fails it will attempt
        to fall back to SSH1.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        pass

    @abstractmethod
    def connect_telnet(self, host, username, password, prompt_endings=("#", ">")):
        """
        Connects to a device via the Telnet protocol.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        pass

    @abstractmethod
    def connect(self, host, username, password, protocol=None, prompt_endings=("#", ">")):
        """
        Attempts to connect to a device by any available protocol, starting with SSH2, then SSH1, then telnet

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param protocol: A string with the desired protocol (telnet, ssh1, ssh2, ssh). If left blank it will try all
                         starting with SSH2, then SSH1 then Telnet.  "ssh" means SSH2 then SSH1.
        :type protocol: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        pass

    @abstractmethod
    def disconnect(self, command="exit"):
        """
        Disconnects the connected session by sending the "exit" command to the remote device.  If that does not make
        the disconnect happen, attempt to force and ungraceful disconnect.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        pass

    @abstractmethod
    def ssh_via_jump(self, host, username, password, options="-o StrictHostKeyChecking=no"):
        """
        From the connected session, this method issues the SSH command to connect to another box, using the main
        connected sessions as a jump point to reach the target.  In other words, connect_ssh() would be used to connect
        to the jump box/bastion host and then this method would be used to connect to the remote device via the jump
        host.

        If this method doesn't receive the expected prompts after issuing the credentials, an exception will be raised.

        :param host: IP address or hostname (resolvable on the jumpbox)
        :type host: str
        :param username: Username to log into the remote device with
        :type username: str
        :param password: Password for logging into the remote device
        :type password: str
        :param options: Additional "ssh" command paramters.  Default disables strict host key checking so that the
                        script will not be prompted to accept the remote key.
        :type options: str
        """
        pass

    @abstractmethod
    def telnet_via_jump(self, host, username, password):
        """
        From the connected session, this method issues the telnet command to connect to another box, using the main
        connected sessions as a jump point to reach the target.  In other words, connect_ssh() would be used to connect
        to the jump box/bastion host and then this method would be used to connect to the remote device via the jump
        host.

        If this method doesn't receive the expected prompts after issuing the credentials, an exception will be raised.

        :param host: IP address or hostname (resolvable on the jumpbox)
        :type host: str
        :param username: Username to log into the remote device with
        :type username: str
        :param password: Password for logging into the remote device
        :type password: str
        """
        pass

    @abstractmethod
    def disconnect_via_jump(self, command="exit"):
        """
        Issues a command to disconnect from the remote device, bringing us back to the jump host.  The default command
        is "exit", but it can be changed by passing in a different "command".  If we don't see the prompt for the jump
        host after issuing the disconnect command, an exception will be raised.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        pass

    @abstractmethod
    def close(self):
        """
        A method to close the SecureCRT tab associated with this CRTSession.
        """
        pass

    @abstractmethod
    def start_cisco_session(self, enable_pass=None):
        """
        Performs initial setup of the session to a Cisco device by detecting parameters (prompt, hostname, network OS,
        etc) of the connected device and modifying the terminal length if configured to do so in the settings file.

        If the device is not at an enable prompt and an enable password is supplied, then this method will also enter
        enable mode on the device before proceeding.

        This should always be called before trying to interact with a Cisco device so that the majority of other
        methods will work correctly.  This should be one of the first calls in a script that is intended to run when
        already connected to the device, or called right after connecting to a device with the "connect_ssh" or similar
        method.

        :param enable_pass: The enable password that should be sent if the device is not in enable mode.
        :type enable_pass: str
        """
        pass

    @abstractmethod
    def end_cisco_session(self):
        """
        End the session by returning the device's terminal parameters that were modified by start_session() to their
        previous values.

        This should always be called before a disconnect (assuming that start_cisco_session was called after connect)
        """
        pass

    @abstractmethod
    def write_output_to_file(self, command, filename):
        """
        Send the supplied command to the remote device and writes the output to a file.

        This function was written specifically to write output line by line because storing large outputs into a
        variable will cause SecureCRT to bog down until it freezes.  A good example is a large "show tech" output.
        This method can handle any length of output

        :param command: The command to be sent to the device
        :type command: str
        :param filename: A string with the absolute path to the filename to be written.
        :type filename: str
        """
        pass

    @abstractmethod
    def get_command_output(self, command):
        """
        Captures the output from the provided command and saves the results in a variable.

        ** NOTE ** Assigning the output directly to a variable causes problems with SecureCRT for long outputs.  It
        will gradually get slower and slower until the program freezes and crashes.  The workaround is to
        save the output directly to a file (line by line), and then read it back into a variable.  This is the
        procedure that this method uses.

        Keyword Arguments:
            :param command: Command string that should be sent to the device
            :type command: str

        :return: The result from issuing the above command.
        :rtype: str
        """
        pass

    @abstractmethod
    def send_config_commands(self, command_list, output_filename=None):
        """
        This method accepts a list of strings, where each string is a command to be sent to the device.

        This method will send "conf t", then all the commands from the list and finally send "end" to the device.
        If an output_filenameThe results returned from entering the commands into the device are written to a file.

        NOTE: This method is new and does not have any error checking for how the remote device handles the commands
        you are trying to send.  USE IT AT YOUR OWN RISK.

        :param command_list: A list of strings, where each string is a command to be sent.  This should NOT include
                            'config t' or 'end'.  This is added automatically.
        :type command_list: list
        :param output_filename: (Optional) If a absolute path to a file is specified, the config session output from
                                applying the commands will be written to this file.
        :type output_filename: str
        """
        pass

    @abstractmethod
    def save(self, command="copy running-config startup-config"):
        """
        Sends a "copy running-config startup-config" command to the remote device to save the running configuration.
        """
        pass


class CRTSession(Session):
    """
    This sub-class of the Session class is used to wrap the SecureCRT API to simplify writing new scripts.  An instance
    of this class represents a tab in SecureCRT and the methods in this class are used to connect to devices,
    disconnect from devices or interact with devices that are connected within the specific SecureCRT tab that this
    object represents.
    """

    def __init__(self, script, tab, from_new_tab=False, prompt_endings=None):
        super(CRTSession, self).__init__()
        self.logger.debug("<SESSION_INIT> Starting creation of CRTSession object")

        self.script = script
        self.tab = tab
        self.screen = tab.Screen
        self.session = tab.Session
        self.response_timeout = 20
        self.jump_endings = None
        self.session_set_sync = False

        if from_new_tab:
            self.logger.debug("<SESSION_INIT> Received tab from ConnectInTab method.")
            self.jump_endings = prompt_endings
        elif not self.is_connected():
            self.logger.debug("<SESSION_INIT> Session not connected prior to creating object.")
        else:
            self.logger.debug("<SESSION_INIT> Session already connected.")

    def __send(self, command):
        if self.is_connected():
            self.screen.Send(command)
            result = self.screen.WaitForString(command.strip(), self.response_timeout)
            if not result:
                self.logger.debug("<__send> Timed out waiting for '{0}' from device.".format(command))
                raise InteractionError("Timed out waiting for sent command to be echoed back to us.")
            else:
                return result
        else:
            self.logger.debug("<__send> Not connected. Error.".format(command))
            raise InteractionError("Session is not connected.  Cannot send command.")

    def __wait_for_string(self, wait_string):
        result = self.screen.WaitForString(wait_string, self.response_timeout)
        if not result:
            self.logger.debug("<__wait_for_string> Timed out waiting for '{0}' from device.".format(wait_string))
            raise InteractionError("Timeout waiting for response from device.")
        else:
            return result

    def __wait_for_strings(self, string_list):
        result = self.screen.WaitForStrings(string_list, self.response_timeout)
        if not result:
            self.logger.debug("<__wait_for_strings> Timed out waiting for '{0}' from device.".format(string_list))
            raise InteractionError("Timeout waiting for response from device.")
        else:
            return result

    def is_connected(self):
        """
        Returns a boolean value that describes if the session is currently connected.

        :return: True if the session is connected, False if not.
        :rtype: bool
        """
        session_connected = self.session.Connected
        if session_connected == 1:
            self.logger.debug("<IS_CONNECTED> Checking Connected Status.  Got: {0} (True)".format(session_connected))
            return True
        else:
            self.logger.debug("<IS_CONNECTED> Checking Connected Status.  Got: {0} (False)".format(session_connected))
            return False

    def __post_connect_check(self, endings):
        """
        Validates that we've gotten to the prompt after a connection is made.

        :param endings: A list of strings, where each string is a possible character that would be found at the end
                        of the CLI prompt for the remote device.
        :type endings: list
        """
        self.logger.debug("<CONN_CHECK> Started looking for following prompt endings: {0}".format(endings))
        at_prompt = False
        while not at_prompt:
            found = self.screen.WaitForStrings(endings, self.response_timeout)
            if not found:
                raise InteractionError("Timeout reached looking for prompt endings: {0}".format(endings))
            else:
                test_string = "!@&^"
                self.screen.Send(test_string + "\b" * len(test_string))
                result = self.screen.WaitForStrings(test_string, self.response_timeout)
                if result:
                    self.logger.debug("<CONN_CHECK> At prompt.  Continuing".format(result))
                    at_prompt = True

    def __connect_ssh_2(self, host, username, password, prompt_endings=("#", "# ", ">")):
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        expanded_endings = []
        for ending in prompt_endings:
            expanded_endings.append("{0}".format(ending))
            expanded_endings.append("{0} ".format(ending))

        ssh2_string = "/SSH2 /ACCEPTHOSTKEYS /L {0} /PASSWORD {1} {2}".format(username, password, host)
        # If the tab is already connected, then give an exception that we cannot connect.
        if self.is_connected():
            self.logger.debug("<CONNECT_SSH2> Session already connected.  Raising exception")
            raise ConnectError("Tab is already connected to another device.")
        else:
            try:
                self.logger.debug("<CONNECT_SSH2> Attempting Connection to: {0}@{1} via SSH2".format(username, host))
                self.session.Connect(ssh2_string)
            except:
                error = self.script.crt.GetLastErrorMessage()
                raise ConnectError(error)

        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT
        self.screen.Synchronous = True
        self.screen.IgnoreEscape = True
        self.logger.debug("<CONNECT_SSH2> Set Synchronous and IgnoreEscape")

        # Make sure banners have printed and we've reached our expected prompt.
        self.__post_connect_check(expanded_endings)

    def __connect_ssh_1(self, host, username, password, prompt_endings=("#", "# ", ">")):
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        expanded_endings = []
        for ending in prompt_endings:
            expanded_endings.append("{0}".format(ending))
            expanded_endings.append("{0} ".format(ending))

        ssh1_string = "/SSH1 /ACCEPTHOSTKEYS /L {0} /PASSWORD {1} {2}".format(username, password, host)
        # If the tab is already connected, then give an exception that we cannot connect.
        if self.is_connected():
            self.logger.debug("<CONNECT_SSH1> Session already connected.  Raising exception")
            raise ConnectError("Tab is already connected to another device.")
        else:
            try:
                self.logger.debug("<CONNECT_SSH1> Attempting Connection to: {0}@{1} via SSH1".format(username, host))
                self.session.Connect(ssh1_string)
            except:
                error = self.script.crt.GetLastErrorMessage()
                raise ConnectError(error)

        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT
        self.screen.Synchronous = True
        self.screen.IgnoreEscape = True
        self.logger.debug("<CONNECT_SSH1> Set Synchronous and IgnoreEscape")

        # Make sure banners have printed and we've reached our expected prompt.
        self.__post_connect_check(expanded_endings)

    def connect_ssh(self, host, username, password, version=None, prompt_endings=("#", ">")):
        """
        Connects to a device via the SSH protocol. By default, SSH2 will be tried first, but if it fails it will attempt
        to fall back to SSH1.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
            user will be prompted for one.
        :type password: str
        :param version: The SSH version to connect with (1 or 2).  Default is None, which will try 2 first and fallback
            to 1 if that fails.
        :type version: int
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        self.logger.debug("<CONNECT_SSH> Attempting Connection to: {0}@{1}".format(username, host))

        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        if version == 2:
            self.__connect_ssh_2(host, username, password, prompt_endings)
        elif version == 1:
            self.__connect_ssh_1(host, username, password, prompt_endings)
        else:
            try:
                self.__connect_ssh_2(host, username, password, prompt_endings)
            except ConnectError as e:
                self.logger.debug("<CONNECT_SSH> Failure trying SSH2: {0}".format(e.message))
                ssh2_error = e.message
                try:
                    self.__connect_ssh_1(host, username, password, prompt_endings)
                except ConnectError as e:
                    ssh1_error = e.message
                    self.logger.debug("<CONNECT_SSH> Failure trying SSH1: {0}".format(e.message))
                    error = "SSH2 and SSH1 failed.\nSSH2 Failure:{0}\nSSH1 Failure:{1}".format(ssh2_error, ssh1_error)
                    raise ConnectError(error)

    def connect_telnet(self, host, username, password, prompt_endings=("#", ">")):
        """
        Connects to a device via the Telent protocol.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        telnet_string = "/TELNET {0}".format(host)
        # If the tab is already connected, then give an exception that we cannot connect.
        if self.is_connected():
            self.logger.debug("<CONNECT_TELNET> Session already connected.  Raising exception")
            raise ConnectError("Tab is already connected to another device.")
        else:
            try:
                self.logger.debug("<CONNECT_TELNET> Attempting Connection to: {0} via TELNET".format(host))
                self.session.Connect(telnet_string)
            except:
                error = self.script.crt.GetLastErrorMessage()
                raise ConnectError(error)

        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT
        self.screen.Synchronous = True
        self.screen.IgnoreEscape = True
        self.logger.debug("<CONNECT_TELNET> Set Synchronous and IgnoreEscape")

        # Handle Login
        self.__wait_for_strings("sername")
        self.__send("{0}\n".format(username))
        self.__wait_for_string("assword")
        self.screen.Send("{0}\n".format(password))

        # Make sure banners have printed and we've reached our expected prompt.
        self.__post_connect_check(prompt_endings)

    def connect(self, host, username, password, protocol=None, prompt_endings=("#", ">")):
        """
        Attempts to connect to a device by any available protocol, starting with SSH2, then SSH1, then telnet

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param protocol: A string with the desired protocol (telnet, ssh1, ssh2, ssh). If left blank it will try all
                         starting with SSH2, then SSH1 then Telnet.  "ssh" means SSH2 then SSH1.
        :type protocol: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        if not protocol:
            try:
                self.connect_ssh(host, username, password, prompt_endings=prompt_endings)
            except ConnectError:
                try:
                    self.connect_telnet(host, username, password, prompt_endings=prompt_endings)
                except ConnectError:
                    raise ConnectError("Unable to make a connection with either SSH or Telnet")
        elif protocol.lower() == "ssh":
            self.connect_ssh(host, username, password, prompt_endings=prompt_endings)
        elif protocol.lower() == "ssh2":
            self.connect_ssh(host, username, password, version=2, prompt_endings=prompt_endings)
        elif protocol.lower() == "ssh1":
            self.connect_ssh(host, username, password, version=1, prompt_endings=prompt_endings)
        elif protocol.lower() == "telnet":
            self.connect_telnet(host, username, password, prompt_endings=prompt_endings)
        else:
            raise ConnectError("Unknown protocol specified.")

    def disconnect(self, command="exit"):
        """
        Disconnects the connected session by sending the "exit" command to the remote device.  If that does not make
        the disconnect happen, attempt to force and ungraceful disconnect.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        self.logger.debug("<DISCONNECT> Sending '{0}' command.".format(command))
        self.__send("{0}\n".format(command))

        # Unset Sync and IgnoreEscape upon disconnect
        self.screen.Synchronous = False
        self.screen.IgnoreEscape = False

        # Give a little time and check if we are disconnected.  If not, force it.
        time.sleep(0.25)
        attempts = 0
        while self.is_connected() and attempts < 10:
            self.logger.debug("<DISCONNECT> Not disconnected.  Attempting ungraceful disconnect.")
            self.session.Disconnect()
            time.sleep(0.1)
            attempts += 1
        if attempts >= 10:
            raise ConnectError("Unable to disconnect from session.")

    def close(self):
        """
        A method to close the SecureCRT tab associated with this CRTSession.
        """
        if self.tab.Index != self.script.crt.GetScriptTab().Index:
            self.tab.Close()

    def ssh_via_jump(self, host, username, password, options="-o StrictHostKeyChecking=no", prompt_endings=("#", ">")):
        """
        From the connected session, this method issues the SSH command to connect to another box, using the main
        connected sessions as a jump point to reach the target.  In other words, connect_ssh() would be used to connect
        to the jump box/bastion host and then this method would be used to connect to the remote device via the jump
        host.

        If this method doesn't receive the expected prompts after issuing the credentials, an exception will be raised.

        :param host: IP address or hostname (resolvable on the jumpbox)
        :type host: str
        :param username: Username to log into the remote device with
        :type username: str
        :param password: Password for logging into the remote device
        :type password: str
        :param options: Additional "ssh" command paramters.  Default disables strict host key checking so that the
                        script will not be prompted to accept the remote key.
        :type options: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not self.prompt:
            self.prompt = self.__get_prompt()
        self.__send("ssh {0} {1}@{2}\n".format(options, username, host))
        result = self.__wait_for_strings(["assword", "refused", "denied"])
        if result == 1:
            self.screen.Send("{0}\n".format(password))
            self.__post_connect_check(prompt_endings)
            self.prompt_stack.insert(0, self.prompt)
        else:
            raise ConnectError("SSH connection refused.")

    def telnet_via_jump(self, host, username, password, prompt_endings=("#", ">")):
        """
        From the connected session, this method issues the telnet command to connect to another box, using the main
        connected sessions as a jump point to reach the target.  In other words, connect_ssh() would be used to connect
        to the jump box/bastion host and then this method would be used to connect to the remote device via the jump
        host.

        If this method doesn't receive the expected prompts after issuing the credentials, an exception will be raised.

        :param host: IP address or hostname (resolvable on the jumpbox)
        :type host: str
        :param username: Username to log into the remote device with
        :type username: str
        :param password: Password for logging into the remote device
        :type password: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not self.prompt:
            self.prompt = self.__get_prompt()
        self.__send("telnet {0}\n".format(host))
        result = self.__wait_for_strings(["sername", "refused", "denied"])
        if result == 1:
            self.__send("{0}\n".format(username))
            self.__wait_for_string("assword")
            self.screen.Send("{0}\n".format(password))
            self.__post_connect_check(prompt_endings)
            self.prompt_stack.insert(0, self.prompt)
        else:
            raise ConnectError("Telnet connection refused.")

    def disconnect_via_jump(self, command="exit"):
        """
        Issues a command to disconnect from the remote device, bringing us back to the jump host.  The default command
        is "exit", but it can be changed by passing in a different "command".  If we don't see the prompt for the jump
        host after issuing the disconnect command, an exception will be raised.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        try:
            prev_prompt = self.prompt_stack.pop(0)
        except IndexError:
            prev_prompt = None
        self.__send("{0}\n".format(command))
        self.__wait_for_string(prev_prompt)

    def start_cisco_session(self, enable_pass=None):
        """
        Performs initial setup of the session to a Cisco device by detecting parameters (prompt, hostname, network OS,
        etc) of the connected device and modifying the terminal length if configured to do so in the settings file.

        If the device is not at an enable prompt and an enable password is supplied, then this method will also enter
        enable mode on the device before proceeding.

        This should always be called before trying to interact with a Cisco device so that the majority of other
        methods will work correctly.  This should be one of the first calls in a script that is intended to run when
        already connected to the device, or called right after connecting to a device with the "connect_ssh" or similar
        method.

        :param enable_pass: The enable password that should be sent if the device is not in enable mode.
        :type enable_pass: str
        """
        # Validate we are connected before trying to start a Cisco session
        if not self.is_connected():
            raise InteractionError("Session is not connected.  Cannot start Cisco session.")

        prompt_for_enable = False
        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT, if manually connected session
        # (i.e. it hasn't been set yet)
        if not self.screen.Synchronous:
            self.session_set_sync = True
            self.screen.Synchronous = True
            self.screen.IgnoreEscape = True
            prompt_for_enable = True
            self.logger.debug("<START> Set Synchronous and IgnoreEscape and Prompt For Enable")

        # Get prompt (and thus hostname) from device
        self.prompt = self.__get_prompt()
        self.__enter_enable(enable_pass, prompt_for_enable)
        self.hostname = self.prompt[:-1]
        self.logger.debug("<START> Set Hostname: {0}".format(self.hostname))

        # Detect the OS of the device, because outputs will differ per OS
        self.os = self.__get_network_os()
        self.logger.debug("<START> Discovered OS: {0}".format(self.os))

        # Get terminal length and width, so we can revert back after changing them.
        self.term_len, self.term_width = self.__get_term_info()
        self.logger.debug("<START> Discovered Term Len: {0}, Term Width: {1}".format(self.term_len, self.term_width))

        # If modify_term setting is True, then prevent "--More--" prompt (length) and wrapping of lines (width)
        if self.script.settings.getboolean("Global", "modify_term"):
            self.logger.debug("<START> Modify Term setting is set.  Sending commands to adjust terminal")
            if self.os == "IOS" or self.os == "NXOS":
                # Send term length command and wait for prompt to return
                if self.term_len:
                    self.__send('term length 0\n')
                    self.__wait_for_string(self.prompt)
            elif self.os == "ASA":
                if self.term_len:
                    self.__send('terminal pager 0\r\n')
                    self.__wait_for_string(self.prompt)

            # Send term width command and wait for prompt to return (depending on platform)

            if self.os == "IOS":
                if self.term_len:
                    self.__send('term width 0\n')
                    self.__wait_for_string(self.prompt)
            elif self.os == "NXOS":
                if self.term_len:
                    self.__send('term width 511\n')
                    self.__wait_for_string(self.prompt)

        # Added due to Nexus echoing twice if system hangs and hasn't printed the prompt yet.
        # Seems like maybe the previous WaitFor prompt isn't always working correctly.  Something to look into.
        time.sleep(0.1)

    def end_cisco_session(self):
        """
        End the session by returning the device's terminal parameters that were modified by start_session() to their
        previous values.

        This should always be called before a disconnect (assuming that start_cisco_session was called after connect)
        """

        # If the 'tab' and 'prompt' options aren't in the session structure, then we aren't actually connected to a
        # device when this is called, and there is nothing to do.
        self.logger.debug("<END> Ending Session")
        if self.tab:
            if self.prompt:
                if self.script.settings.getboolean("Global", "modify_term"):
                    self.logger.debug("<END> Modify Term setting is set.  Sending commands to return terminal "
                                      "to normal.")
                    if self.os == "IOS" or self.os == "NXOS":
                        if self.term_len:
                            # Set term length back to saved values
                            self.__send('term length {0}\n'.format(self.term_len))
                            self.__wait_for_string(self.prompt)

                        if self.term_width:
                            # Set term width back to saved values
                            self.__send('term width {0}\n'.format(self.term_width))
                            self.__wait_for_string(self.prompt)
                    elif self.os == "ASA":
                        self.screen.Send("terminal pager {0}\n".format(self.term_len))

            self.prompt = None
            self.logger.debug("<END> Deleting learned Prompt.")
            self.hostname = None
            self.logger.debug("<END> Deleting learned Hostname.")

            # Delete the detected OS
            self.os = None
            self.logger.debug("<END> Deleting Discovered OS.")

            # Return SecureCRT Synchronous and IgnoreEscape values back to defaults, if needed.
            if self.session_set_sync:
                self.screen.Synchronous = False
                self.screen.IgnoreEscape = False
                self.session_set_sync = False
                self.logger.debug("<END> Unset Synchronous and IgnoreEscape")

    def __enter_enable(self, enable_pass, prompt=False):
        """
        A function that will attempt to enter enable mode, if we aren't in enable mode when the method is called.

        :param enable_pass: The enable password to use for the connected device.
        :type enable_pass: str
        """
        if self.prompt[-1] == "#":
            self.logger.debug("<__enter_enable> Already in enable -- Moving on.")
        elif self.prompt[-1] == ">":
            if not enable_pass and prompt:
                enable_pass = self.script.prompt_window("Please enter enable password.", "Enter Enable PW",
                                                        hide_input=True)
            if enable_pass:
                self.logger.debug("<__enter_enable> Not in enable.  Attempting to elevate privilege.")
                self.__send("enable\n")
                result = self.__wait_for_strings(["% No", "assword", ">"])
                if result == 1:
                    self.logger.debug("<__enter_enable> Enable password not set.")
                    raise InteractionError("Unable to enter Enable mode. No password set.")
                if result == 2:
                    self.screen.Send("{0}\n".format(enable_pass))
                    self.__wait_for_string("#")
                    self.prompt = self.__get_prompt()
                else:
                    self.logger.debug("<__enter_enable> Failed to detect password prompt after issuing 'enable'.")
                    raise InteractionError("Unable to enter Enable mode.")
            else:
                self.logger.debug("<__enter_enable> Not in enable mode and no enable password given.  Cannot proceed.")
                raise InteractionError("Not in enable mode and no enable password given.  Cannot proceed.")
        else:
            self.logger.debug("<__enter_enable> Unable to recognize Cisco style prompt.")
            raise InteractionError("Unable to recognize Cisco style prompt")

    def __get_prompt(self):
        """
        Discovers the prompt of the remote device and returns it.
        """
        self.logger.debug("<GET PROMPT> Attempting to discover device prompt.")

        result = ''
        attempts = 0
        while result == '' and attempts < 3:
            test_string = "\n!&%\b\b\b"
            timeout_seconds = 2
            self.screen.Send(test_string)
            result = self.screen.ReadString("!&%", timeout_seconds)
            attempts += 1
            self.logger.debug("<CONNECT> Attempt {0}: Prompt result = {1}".format(attempts, result))

        prompt = result.strip(u"\r\n\b ")
        if prompt == '':
            self.logger.debug("<GET PROMPT> Prompt discovery failed.  Raising exception.")
            raise InteractionError("Unable to discover device prompt")

        self.logger.debug("<GET PROMPT> Discovered prompt as '{0}'.".format(prompt))
        return prompt

    def __get_network_os(self):
        """
        Discovers Network OS type so that scripts can make decisions based on the information, such as sending a
        different version of a command for a particular OS.
        """
        send_cmd = "show version | i Cisco"

        raw_version = self.__get_output(send_cmd)
        self.logger.debug("<GET OS> Version String: {0}".format(raw_version))

        if "IOS XE" in raw_version:
            version = "IOS"
        elif "Cisco IOS Software" in raw_version or "Cisco Internetwork Operating System" in raw_version:
            version = "IOS"
        elif "Cisco Nexus Operating System" in raw_version:
            version = "NXOS"
        elif "Adaptive Security Appliance" in raw_version:
            version = "ASA"
        else:
            self.logger.debug("<GET OS> Error detecting OS.  Raising Exception.")
            raise InteractionError("Unknown or Unsupported device OS.")

        return version

    def __get_term_info(self):
        """
        Returns the current terminal length and width, by capturing the output from the relevant commands.

        :return: A 2-tuple containing the terminal length and the terminal width
        """
        re_num_exp = r'\d+'
        re_num = re.compile(re_num_exp)

        if self.os == "IOS" or self.os == "NXOS":
            result = self.__get_output("show terminal | i Length")
            term_info = result.split(',')

            re_length = re_num.search(term_info[0])
            if re_length:
                length = re_length.group(0)
            else:
                length = None

            re_width = re_num.search(term_info[1])
            if re_width:
                width = re_width.group(0)
            else:
                width = None

            return length, width

        elif self.os == "ASA":
            pager = self.__get_output("show pager")
            re_length = re_num.search(pager)
            if re_length:
                length = re_length.group(0)
            else:
                length = None

            term_info = self.__get_output("show terminal")
            re_width = re_num.search(term_info[1])
            if re_width:
                width = re_width.group(0)
            else:
                width = None

            return length, width

        else:
            return None, None

    def __get_output(self, command):
        """
        A function that issues a command to the current session and returns the output as a string variable.
        *** NOTE *** This is  a private method because it should only be used when it is guaranteed that the output
        will be small (less than 1000 lines), or else SecureCRT can bog down and crash.  "get_command_output()" is safer
        because it avoids the problem by writing the output to a file before reading it back into a variable.

        :param command: Command string that should be sent to the device
        :type command: str

        Variable holding the result of issuing the above command.
        """
        # Send command
        self.__send(command.strip() + '\n')

        # Capture the output until we get our prompt back and write it to the file
        result = self.screen.ReadString(self.prompt)

        return result.strip('\r\n')

    def write_output_to_file(self, command, filename):
        """
        Send the supplied command to the remote device and writes the output to a file.

        This function was written specifically to write output line by line because storing large outputs into a
        variable will cause SecureCRT to bog down until it freezes.  A good example is a large "show tech" output.
        This method can handle any length of output

        :param command: The command to be sent to the device
        :type command: str
        :param filename: A string with the absolute path to the filename to be written.
        :type filename: str
        """
        self.logger.debug("<WRITE_FILE> Call to write_output_to_file with command: {0}, filename: {0}"
                          .format(command, filename))
        self.script.validate_dir(os.path.dirname(filename))
        self.logger.debug("<WRITE_FILE> Using filename: {0}".format(filename))

        # RegEx to match the whitespace and backspace commands after --More-- prompt
        exp_more = r' [\b]+[ ]+[\b]+(?P<line>.*)'
        re_more = re.compile(exp_more)

        # The 3 different types of lines we want to match (MatchIndex) and treat differntly
        if self.os == "IOS" or self.os == "NXOS":
            matches = ["\r\n", '--More--', self.prompt]
        elif self.os == "ASA":
            matches = ["\r\n", '<--- More --->', self.prompt]
        else:
            matches = ["\r\n", '--More--', self.prompt]

        # Write the output to the specified file
        try:
            # Need the 'b' in mode 'wb', or else Windows systems add extra blank lines.
            with open(filename, 'wb') as newfile:
                self.__send(command + "\n")

                # Loop to capture every line of the command.  If we get CRLF (first entry in our "endings" list), then
                # write that line to the file.  If we get our prompt back (which won't have CRLF), break the loop b/c we
                # found the end of the output.
                while True:
                    nextline = self.screen.ReadString(matches, 30)
                    # If the match was the 1st index in the endings list -> \r\n
                    if self.screen.MatchIndex == 1:
                        # Strip newlines from front and back of line.
                        nextline = nextline.strip('\r\n')
                        # If there is something left, write it.
                        if nextline != "":
                            # Check for backspace and spaces after --More-- prompt and strip them out if needed.
                            regex = re_more.match(nextline)
                            if regex:
                                nextline = regex.group('line')
                            # Strip line endings from line.  Also re-encode line as ASCII
                            # and ignore the character if it can't be done (rare error on
                            # Nexus)
                            newfile.write(nextline.strip('\r\n').encode('ascii', 'ignore') + "\r\n")
                            self.logger.debug("<WRITE_FILE> Writing Line: {0}".format(nextline.strip('\r\n')
                                                                                      .encode('ascii', 'ignore')))
                    elif self.screen.MatchIndex == 2:
                        # If we get a --More-- send a space character
                        self.screen.Send(" ")
                    elif self.screen.MatchIndex == 3:
                        # We got our prompt, so break the loop
                        break
                    else:
                        raise InteractionError("Timeout trying to capture output")

        except IOError, err:
            error_str = "IO Error for:\n{0}\n\n{1}".format(filename, err)
            self.script.message_box(error_str, "IO Error", ICON_STOP)

    def get_command_output(self, command):
        """
        Captures the output from the provided command and saves the results in a variable.

        ** NOTE ** Assigning the output directly to a variable causes problems with SecureCRT for long outputs.  It
        will gradually get slower and slower until the program freezes and crashes.  The workaround is to
        save the output directly to a file (line by line), and then read it back into a variable.  This is the
        procedure that this method uses.

        Keyword Arguments:
            :param command: Command string that should be sent to the device
            :type command: str

        :return: The result from issuing the above command.
        :rtype: str
        """
        self.logger.debug("<GET OUTPUT> Running get_command_output with input '{0}'".format(command))

        # Create a temporary filename
        temp_filename = self.create_output_filename("{0}-temp".format(command))
        self.logger.debug("<GET OUTPUT> Temp Filename".format(temp_filename))

        self.write_output_to_file(command, temp_filename)

        with open(temp_filename, 'r') as temp_file:
            result = temp_file.read()

        # If debug mode is enabled, save temporary file to the debug directory.
        if self.script.settings.getboolean("Global", "debug_mode"):
            filename = os.path.split(temp_filename)[1]
            new_filename = os.path.join(self.script.debug_dir, filename)
            self.logger.debug("<GET OUTPUT> Moving temp file to {0}".format(new_filename))
            os.rename(temp_filename, new_filename)
        else:
            self.logger.debug("<GET OUTPUT> Deleting {0}".format(temp_filename))
            os.remove(temp_filename)
        self.logger.debug("<GET OUTPUT> Returning results of size {0}".format(sys.getsizeof(result)))
        return result

    def send_config_commands(self, command_list, output_filename=None):
        """
        This method accepts a list of strings, where each string is a command to be sent to the device.

        This method will send "conf t", then all the commands from the list and finally send "end" to the device.
        If an output_filenameThe results returned from entering the commands into the device are written to a file.

        NOTE: This method is new and does not have any error checking for how the remote device handles the commands
        you are trying to send.  USE IT AT YOUR OWN RISK.

        :param command_list: A list of strings, where each string is a command to be sent.  This should NOT include
                            'config t' or 'end'.  This is added automatically.
        :type command_list: list
        :param output_filename: (Optional) If a absolute path to a file is specified, the config session output from
                                applying the commands will be written to this file.
        :type output_filename: str
        """
        self.logger.debug("<SEND_CMDS> Preparing to write commands to device.")
        self.logger.debug("<SEND_CMDS> Received: {0}".format(str(command_list)))

        # Build text commands to send to device, and book-end with "conf t" and "end"
        config_results = ""
        command_list.insert(0, "configure terminal")

        for command in command_list:
            self.screen.Send("{0}\n".format(command))
            output = self.screen.ReadString(")#", 3)
            if output:
                config_results += "{0})#".format(output)
            else:
                error = "Did not receive expected prompt after issuing command: {0}".format(command)
                self.logger.debug("<SEND_CMDS> {0}".format(error))
                raise InteractionError("{0}".format(error))

        self.screen.Send("end\n")
        output = self.screen.ReadString(self.prompt, 2)
        config_results += "{0}{1}".format(output, self.prompt)

        with open(output_filename, 'w') as output_file:
            self.logger.debug("<SEND_CMDS> Writing config session output to: {0}".format(output_filename))
            output_file.write(config_results.replace("\r", ""))

    def save(self, command="copy running-config startup-config"):
        """
        Sends a "copy running-config startup-config" command to the remote device to save the running configuration.
        """
        self.logger.debug("<SAVE> Saving configuration on remote device.")
        self.__send("{0}\n".format(command))
        save_results = self.__wait_for_strings(["?", self.prompt])
        if save_results == 1:
            self.screen.Send("\n")
        self.logger.debug("<SAVE> Save results: {0}".format(save_results))


class DebugSession(Session):
    """
    This class is used when the scripts are executed directly from a local Python installation instead of from
    SecureCRT.  This class is intended to simulate connectivity to remote devices by prompting the user for what would
    otherwise be extracted from SecureCRT.  For example, when this class tries to get the output from a show command,
    it will instead prompt the user for a location of a file with the associated output.  This allows the scripts to
    be run directly in an IDE for development and troubleshooting of more complicated logic around parsing command
    outputs.
    """

    def __init__(self, script):
        super(DebugSession, self).__init__()
        self.logger.debug("<INIT> Building Direct Session Object")
        self.script = script

        valid_response = ["yes", "no"]
        response = ""
        while response.lower() not in valid_response:
            response = raw_input("Is this device already connected?({0}): ".format(str(valid_response)))

        if response.lower() == "yes":
            self.logger.debug("<INIT> Assuming session is already connected")
            self._connected = True
        else:
            self.logger.debug("<INIT> Assuming session is NOT already connected")
            self._connected = False

    def is_connected(self):
        """
        Returns a boolean value that describes if the session is currently connected.

        :return: True if the session is connected, False if not.
        :rtype: bool
        """
        return self._connected

    def connect_ssh(self, host, username, password, version=None, prompt_endings=("#", ">")):
        """
        Pretends to connect to a device via SSH.  Simply tracks that we are now connected to something within this
        session (this method never fails).

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
            user will be prompted for one.
        :type password: str
        :param version: The SSH version to connect with (1 or 2).  Default is None, which will try 2 first and fallback
            to 1 if that fails.
        :type version: int
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if version == 2 or version == 1:
            print "Pretending to log into device {0} with username {1} using SSH{2}.".format(host, username, version)
        else:
            print "Pretending to log into device {0} with username {1} using SSH2.".format(host, username)
        self.hostname = host
        self.prompt = host + "#"
        self._connected = True

    def connect_telnet(self, host, username, password, prompt_endings=("#", ">")):
        """
        Pretends to connect to a device via the Telnet protocol, just like connect_ssh above.  Never fails.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        print "Pretending to log into device {0} with username {1} using TELNET.".format(host, username)
        self.hostname = host
        self.prompt = host + "#"
        self._connected = True

    def connect(self, host, username, password, protocol=None, prompt_endings=("#", ">")):
        """
        Pretends to connect to a device.  Simply marks the state of the session as connected.  Never fails.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param protocol: A string with the desired protocol (telnet, ssh1, ssh2, ssh). If left blank it will try all
                         starting with SSH2, then SSH1 then Telnet.  "ssh" means SSH2 then SSH1.
        :type protocol: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not protocol:
            print "Pretending to log into device {0} with username {1} using ANY.".format(host, username, protocol)
        else:
            print "Pretending to log into device {0} with username {1} using {2}.".format(host, username, protocol)
        self._connected = True

    def disconnect(self, command="exit"):
        """
        Pretends to disconnects the connected session.  Simply marks our session as disconnected.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        print "Pretending to disconnect from device {0}.".format(self.hostname)
        self._connected = False

    def ssh_via_jump(self, host, username, password, options="-o StrictHostKeyChecking=no"):
        """
        Pretends to connect to a device via SSH through a fictitious jump box.  Never fails unless our session isn't
        marked as currently connected.

        :param host: IP address or hostname (resolvable on the jumpbox)
        :type host: str
        :param username: Username to log into the remote device with
        :type username: str
        :param password: Password for logging into the remote device
        :type password: str
        :param options: Additional "ssh" command paramters.  Default disables strict host key checking so that the
                        script will not be prompted to accept the remote key.
        :type options: str
        """
        if self.is_connected():
            if self.prompt:
                self.prompt_stack.insert(0,self.prompt)
            self.prompt = "{0}#".format(host)
            print "Now connected to: {0} (using prompt: {1})".format(host, self.prompt)
        else:
            raise ConnectError("Not connected to a jumpbox")

    def telnet_via_jump(self, host, username, password):
        """
        Pretends to connect to a device via telnet through a fictitious jump box.  Never fails unless our session isn't
        marked as currently connected.

        :param host: IP address or hostname (resolvable on the jumpbox)
        :type host: str
        :param username: Username to log into the remote device with
        :type username: str
        :param password: Password for logging into the remote device
        :type password: str
        """
        if self.is_connected():
            if self.prompt:
                self.prompt_stack.insert(0,self.prompt)
            self.prompt = "{0}#".format(host)
            print "Now connected to: {0} (using prompt: {1})".format(host, self.prompt)
        else:
            raise ConnectError("Not connected to a jumpbox")

    def disconnect_via_jump(self, command="exit"):
        """
        Pretends to disconnect from a device connect through a jump box.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        prev_prompt = None
        try:
            prev_prompt = self.prompt_stack.pop(0)
            print "Simulated disconnect from remote host.  Now at prompt: {0}".format(prev_prompt)
            self.prompt = prev_prompt
        except IndexError:
            print "Simulated disconnect from remote host.  Prompt not recorded from previous device".format
            self.prompt = prev_prompt

    def close(self):
        """
        A method to close the SecureCRT tab associated with this CRTSession.  Does nothing but print to the console.
        """
        print "Closing tab."

    def start_cisco_session(self, enable_pass=None):
        """
        Performs initial setup of the session to a Cisco device by detecting parameters (prompt, hostname, network OS,
        etc) of the connected device and modifying the terminal length if configured to do so in the settings file.

        Always assumes that we are already in enable mode (privilege 15)

        This should always be called before trying to interact with a Cisco device so that the majority of other
        methods will work correctly.  This should be one of the first calls in a script that is intended to run when
        already connected to the device, or called right after connecting to a device with the "connect_ssh" or similar
        method.

        :param enable_pass: The enable password that should be sent if the device is not in enable mode.
        :type enable_pass: str
        """
        # Validate we are connected before trying to start a Cisco session
        if not self.is_connected():
            raise InteractionError("Session is not connected.  Cannot start Cisco session.")

        # Get prompt (and thus hostname) from device
        self.prompt = "DebugHost#"
        self.hostname = self.prompt[:-1]
        self.logger.debug("<START> Set Hostname: {0}".format(self.hostname))

        # Detect the OS of the device, because outputs will differ per OS
        valid_os = ["IOS", "NXOS", "ASA"]
        response = ""
        while response not in valid_os:
            response = raw_input("Select OS ({0}): ".format(str(valid_os)))
        self.logger.debug("<INIT> Setting OS to {0}".format(response))
        self.os = response

        # Get terminal length and width, so we can revert back after changing them.
        self.term_len, self.term_width = None, None

        # If modify_term setting is True, then prevent "--More--" prompt (length) and wrapping of lines (width)
        if self.script.settings.getboolean("Global", "modify_term"):
            self.logger.debug("<START> Pretending to modify term setting.")

    def end_cisco_session(self):
        """
        End the session by returning the device's terminal parameters that were modified by start_session() to their
        previous values.

        This should always be called before a disconnect (assuming that start_cisco_session was called after connect)
        """
        self.logger.debug("<END> Ending Session")

        # Delete prompt and hostname attributes
        self.prompt = None
        self.logger.debug("<END> Deleting learned Prompt.")
        self.hostname = None
        self.logger.debug("<END> Deleting learned Hostname.")

        # Delete the detected OS
        self.os = None
        self.logger.debug("<END> Deleting Discovered OS.")

    def write_output_to_file(self, command, filename):
        """
        Send the supplied command to the remote device and writes the output to a file.

        This function was written specifically to write output line by line because storing large outputs into a
        variable will cause SecureCRT to bog down until it freezes.  A good example is a large "show tech" output.
        This method can handle any length of output

        :param command: The command to be sent to the device
        :type command: str
        :param filename: A string with the absolute path to the filename to be written.
        :type filename: str
        """
        input_filename = ""
        while not os.path.isfile(input_filename):
            input_filename = raw_input("Path to file with output from '{0}' ('q' to quit): ".format(command))
            if input_filename == 'q':
                exit(0)
            elif not os.path.isfile(input_filename):
                print "Invalid File, please try again..."

        with open(input_filename, 'r') as input_file:
            input_data = input_file.readlines()

        self.logger.debug("<WRITE OUTPUT> Call to write_output_to_file with command: {0}, filename: {1}"
                          .format(command, filename))
        self.script.validate_dir(os.path.dirname(filename))
        self.logger.debug("<WRITE OUTPUT> Using filename: {0}".format(filename))

        # Write the output to the specified file
        try:
            # Need the 'b' in mode 'wb', or else Windows systems add extra blank lines.
            with open(filename, 'wb') as newfile:
                for line in input_data:
                    newfile.write(line.strip('\r\n').encode('ascii', 'ignore') + "\r\n")
                    self.logger.debug("<WRITE OUTPUT> Writing Line: {0}".format(line.strip('\r\n')
                                                                                .encode('ascii', 'ignore')))
        except IOError, err:
            error_str = "IO Error for:\n{0}\n\n{1}".format(filename, err)
            self.script.message_box(error_str, "IO Error", ICON_STOP)

    def get_command_output(self, command):
        """
        Captures the output from the provided command and saves the results in a variable.

        ** NOTE ** Assigning the output directly to a variable causes problems with SecureCRT for long outputs.  It
        will gradually get slower and slower until the program freezes and crashes.  The workaround is to
        save the output directly to a file (line by line), and then read it back into a variable.  This is the
        procedure that this method uses.

        Keyword Arguments:
            :param command: Command string that should be sent to the device
            :type command: str

        :return: The result from issuing the above command.
        :rtype: str
        """
        self.logger.debug("<GET OUTPUT> Running get_command_output with input {0}".format(command))
        # Create a temporary filename
        temp_filename = self.create_output_filename("{0}-temp".format(command))
        self.logger.debug("<GET OUTPUT> Temp Filename".format(temp_filename))
        self.write_output_to_file(command, temp_filename)
        with open(temp_filename, 'r') as temp_file:
            result = temp_file.read()

        if self.script.settings.getboolean("Global", "debug_mode"):
            filename = os.path.split(temp_filename)[1]
            new_filename = os.path.join(self.script.debug_dir, filename)
            self.logger.debug("<GET OUTPUT> Moving temp file to {0}".format(new_filename))
            os.rename(temp_filename, new_filename)
        else:
            self.logger.debug("<GET OUTPUT> Deleting {0}".format(temp_filename))
            os.remove(temp_filename)
        self.logger.debug("<GET OUTPUT> Returning results of size {0}".format(sys.getsizeof(result)))
        return result

    def send_config_commands(self, command_list, output_filename=None):
        """
        This method accepts a list of strings, where each string is a command to be sent to the device.

        This method will pretend to send "conf t", then all the commands from the list and finally send "end" to the
        device. If an output_filename is specified, the (fake) results returned from entering the commands into the
        (fake) device are written to a file.

        :param command_list: A list of strings, where each string is a command to be sent.  This should NOT include
                            'config t' or 'end'.  This is added automatically.
        :type command_list: list
        :param output_filename: (Optional) If a absolute path to a file is specified, the config session output from
                                applying the commands will be written to this file.
        :type output_filename: str
        """
        self.logger.debug("<SEND CONFIG> Preparing to write commands to device.")
        self.logger.debug("<SEND CONFIG> Received: {0}".format(str(command_list)))

        command_string = ""
        command_string += "configure terminal\n"
        for command in command_list:
            command_string += "{0}\n".format(command.strip())
        command_string += "end\n"

        self.logger.debug("<SEND CONFIG> Final command list:\n {0}".format(command_string))

        output_filename = self.create_output_filename("CONFIG_RESULT")
        config_results = command_string
        with open(output_filename, 'w') as output_file:
            self.logger.debug("<SEND CONFIG> Writing output to: {0}".format(output_filename))
            output_file.write("{0}{1}".format(self.prompt, config_results))

    def save(self, command="copy running-config startup-config"):
        """
        Pretends to send a "copy running-config startup-config" command to the remote device to save the running
        configuration.  Only prints to the console.
        """
        self.logger.debug("<SAVE> Simulating Saving configuration on remote device.")
        print "Saved config."
