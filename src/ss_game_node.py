#!/usr/bin/env python

# Jacqueline Kory Westlund
# May 2016
#
# The MIT License (MIT)
#
# Copyright (c) 2016 Personal Robots Group
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys # exit and argv
import json # for reading config file
import rospy # ROS
import argparse # to parse command line arguments
import signal # catching SIGINT signal
import logging # log messages
import Queue # for getting messages from ROS callback threads
import datetime # for getting time deltas for timeouts
from ss_script_handler import ss_script_handler # plays back script lines
from ss_ros import ss_ros # we put all our ROS stuff here

class ss_game_node():
    """ The SAR social stories main game node orchestrates the game: what the
    robot is told to do, what is loaded on the tablet, what to do in response
    to stuff that happens on the tablet or from other sensors.

    This node sends ROS messages to a SAR Opal game via a rosbridge_server
    websocket connection, and uses ROS to exchange messages with other relevant
    nodes (such as the node that translates robot commands to specific robot
    platforms).
    """

    # Set up ROS node globally.
    # TODO If running on network where DNS does not resolve local
    # hostnames, get the public IP address of this machine and
    # export to the environment variable $ROS_IP to set the public
    # address of this node, so the user doesn't have to remember
    # to do this before starting the node.
    ros_node = rospy.init_node('social_story_game', anonymous=True)
            # We could set the ROS log level here if we want:
            #log_level=rospy.DEBUG)
            # The rest of our logging is set up in the log config file.

    def __init__(self):
        """ Initialize anything that needs initialization """
        # Set up queue that we use to get messages from ROS callbacks.
        self.queue = Queue.Queue()
        # Set up logger.
        self.logger = logging.getLogger(__name__)
        # Configure logging.
        try:
            config_file = "ss_log_config.json"
            with open(config_file) as json_file:
                json_data = json.load(json_file)
                logging.config.dictConfig(json_data)
                self.logger.debug("==============================\n" +
                    "STARTING\nLogger configuration:\n %s", json_data)
        except Exception as e:
            # Could not read config file -- use basic configuration.
            logging.basicConfig(filename="ss.log",
                    level=logging.DEBUG)
            self.logger.exception("ERROR! Could not read your json log "
                + "config file \"" + config_file + "\". Does the file "
                + "exist? Is it valid json?\n\nUsing default log setup to "
                + "log to \"ss.log\". Will not be logging to rosout!")


    def parse_arguments_and_launch(self):
        # Parse python arguments.
        # The game node requires the session number and participant ID be
        # provided so the appropriate game scripts can be loaded.
        parser = argparse.ArgumentParser(
                formatter_class=argparse.RawDescriptionHelpFormatter,
                description='Start the SAR Social Stories game node, which '
                + 'orchestrates the game: loads scripts, uses ROS to tell the '
                + 'robot and tablet what to do.\nRequires roscore to be running'
                + ' and requires rosbridge_server for communication with the '
                + 'SAR opal tablet (where game content is shown).')
        parser.add_argument('session', action='store',
               nargs='?', type=int, default=-1, help='Indicate which session'
               + ' this is so the appropriate game scripts can be loaded.')
        parser.add_argument('participant',
               action='store', nargs='?', type=str, default='DEMO', help=
               'Indicate which participant this is so the appropriate game '
               + 'scripts can be loaded.')

        # Parse the args we got, and print them out.
        args = parser.parse_args()
        self.logger.debug("Args received: %s", args)

        # Give the session number and participant ID to the game launcher
        # where they will be used to load appropriate game scripts.
        #
        # If the session number doesn't make sense, or we've specified that
        # this is a demo, run demo.
        if args.session < 0 or args.participant == 'DEMO':
            self.launch_game(-1, 'DEMO')
        # Otherwise, launch the game for the provided session and ID
        else:
            self.launch_game(args.session, args.participant)


    def launch_game(self, session, participant):
        """ Load game based on the current session and participant """
        # Log session and participant ID.
        self.logger.info("==============================\nSOCIAL STORIES " +
            "GAME\nSession: %s, Participant ID: %s", session, participant)

        # Set up ROS node publishers and subscribers.
        self.ros_ss = ss_ros(self.ros_node, self.queue)

        # Read config file to get relative file path to game scripts.
        try:
            config_file = "ss_config.demo.json" if participant == "DEMO" \
                    else "ss_config.json"
            with open(config_file) as json_file:
                json_data = json.load(json_file)
                self.logger.debug("Reading game config file...: %s", json_data)
                if ("script_path" in json_data):
                    self.script_path = json_data["script_path"]
                else:
                    self.logger.error("Could not read relative path to game "
                        + "scripts! Expected option \"script_path\" to be in "
                        + "the config file. Exiting because we need the "
                        + "scripts to run the game.")
                    return
                if ("story_script_path" in json_data):
                    self.story_script_path = json_data["story_script_path"]
                else:
                    self.logger.error("Could not read path to story scripts! "
                        + "Expected option \"story_script_path\" to be in "
                        + "config file. Assuming story scripts are in the main"
                        + " game script directory and not a sub-directory.")
                    self.story_script_path = None
                if ("session_script_path" in json_data):
                    self.session_script_path = json_data["session_script_path"]
                else:
                    self.logger.error("Could not read path to session scripts! "
                        + "Expected option \"session_script_path\" to be in "
                        + "config file. Assuming session scripts are in the main"
                        + "game script directory and not a sub-directory.")
                    self.session_script_path = None
                if ("database") in json_data:
                    database = json_data["database"]
                else:
                    self.logger.error("""Could not read name of database!
                        Expected option \"database\" to be in the config file.
                        Assuming database is named \"socialstories.db\"""")
                    database = "socialstories.db"
                if ("percent_correct_to_level") in json_data:
                    percent_correct_to_level = json_data[
                            "percent_correct_to_level"]
                else:
                    self.logger.error("""Could not read the percent questions
                        correct needed to level! Expected option
                        \"percent_correct_to_level\" to be in the config file.
                        Defaulting to 75%.""")
                    percent_correct_to_level = 0.75
        except Exception as e:
            self.logger.exception("Could not read your json config file \""
                + config_file + "\". Does the file exist? Is it valid json?"
                + " Exiting because we need the config file to run the game.")
            return

        # Load script.
        try:
            self.script_handler = ss_script_handler(self.ros_ss, session,
                participant, self.script_path, self.story_script_path,
                self.session_script_path, database, percent_correct_to_level)
        except IOError as e:
            self.logger.exception("Did not load the session script... exiting "
                + "because we need the session script to run the game.")
            return
        else:
            # Flag to indicate whether we should exit.
            self.stop = False

            # Flags for game control.
            started = False
            paused = False
            log_timer = datetime.datetime.now()

            # Set up signal handler to catch SIGINT (e.g., ctrl-c).
            signal.signal(signal.SIGINT, self.signal_handler)

            while (not self.stop):
                try:
                    try:
                        # Get data from queue if any is there, but don't
                        # wait if there isn't.
                        msg = self.queue.get(False)
                    except Queue.Empty:
                        # no data yet!
                        pass
                    else:
                        # Got a message! Parse:
                        # Wait for START command before starting to
                        # iterate over the script.
                        if "START" in msg and not started:
                            self.logger.info("Starting game!")
                            started = True
                            # announce the game is starting
                            self.ros_ss.send_game_state("START")
                            self.ros_ss.send_game_state("IN_PROGRESS")

                        # If we get a PAUSE command, pause iteration over
                        # the script.
                        if "PAUSE" in msg and not paused:
                            self.logger.info("Game paused!")
                            log_timer = datetime.datetime.now()
                            paused = True
                            self.script_handler.pause_game_timer()
                            # announce the game is pausing
                            self.ros_ss.send_game_state("PAUSE")

                        # If we are paused and get a CONTINUE command,
                        # we can resume iterating over the script. If
                        # we're not paused, ignore.
                        if "CONTINUE" in msg and paused:
                            self.logger.info("Resuming game!")
                            paused = False
                            self.script_handler.resume_game_timer()
                            # announce the game is resuming
                            self.ros_ss.send_game_state("IN_PROGRESS")

                        # When we receive an END command, we need to
                        # exit gracefully. Stop all repeating scripts
                        # and story scripts, go directly to the end.
                        if "END" in msg and started:
                            self.logger.info("Ending game!")
                            self.script_handler.set_end_game()

                    # If the game has been started and is not paused,
                    # parse and handle the next script line.
                    if started and not paused:
                        self.script_handler.iterate_once()

                    elif not started or paused:
                        # Print a log message periodically stating that
                        # we are waiting for a command to continue.
                        if (datetime.datetime.now() - log_timer > \
                                datetime.timedelta(seconds=int(5))):
                            if paused:
                                self.logger.info("Game paused... waiting for "
                                + "command to continue.")
                            elif not started:
                                self.logger.info("Waiting for command to "
                                    + "start.")
                            log_timer = datetime.datetime.now()

                except StopIteration as e:
                    self.logger.info("Finished script!")
                    # Send message to announce the game is over.
                    if "performance" in dir(e):
                        self.ros_ss.send_game_state("END", e.performance)
                    else:
                        self.ros_ss.send_game_state("END")
                    break

            # TODO wait after exiting this loop for the main
            # SessionManager to close the process??


    def signal_handler(self, sig, frame):
        """ Handle signals caught """
        if sig == signal.SIGINT:
            self.logger.info("Got keyboard interrupt! Exiting.")
            self.stop = True
            exit("Interrupted by user.")


if __name__ == '__main__':
    # Try launching the game!
    try:
        game_node = ss_game_node()
        game_node.parse_arguments_and_launch()

    # If roscore isn't running or shuts down unexpectedly...
    except rospy.ROSInterruptException:
        self.logger.exception('ROS node shutdown')
        pass

