#!/usr/bin/env python
#
# corenlp  - Python interface to Stanford Core NLP tools
# Copyright (c) 2012 Dustin Smith
#   https://github.com/dasmith/stanford-corenlp-python
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


import json, optparse, os, re, sys, time, traceback
import pexpect
import tempfile
import shutil
from progressbar import ProgressBar, Fraction
from unidecode import unidecode
from subprocess import call

VERBOSE = False
STATE_START, STATE_TEXT, STATE_WORDS, STATE_TREE, STATE_DEPENDENCY, STATE_COREFERENCE = 0, 1, 2, 3, 4, 5
WORD_PATTERN = re.compile('\[([^\]]+)\]')
CR_PATTERN = re.compile(r"\((\d*),(\d)*,\[(\d*),(\d*)\)\) -> \((\d*),(\d)*,\[(\d*),(\d*)\)\), that is: \"(.*)\" -> \"(.*)\"")

class bc:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'


class ProcessError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class ParserError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class TimeoutError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


def init_corenlp_command(corenlp_path, memory):
    """
    Checks the location of the jar files.
    Spawns the server as a process.
    """


    # TODO: Can edit jar constants
    jars = ["stanford-corenlp-3.2.0.jar",
            "stanford-corenlp-3.2.0-models.jar",
            "xom.jar",
            "joda-time.jar",
            "jollyday.jar"]

    java_path = "java"
    classname = "edu.stanford.nlp.pipeline.StanfordCoreNLP"
    # include the properties file, so you can change defaults
    # but any changes in output format will break parse_parser_results()
    property_name = "default.properties"
    current_dir_pr = os.path.dirname(os.path.abspath( __file__ )) +"/"+ property_name
    if os.path.exists(property_name):
        props = "-props %s" % (property_name)
    elif os.path.exists(current_dir_pr):
        props = "-props %s" % (current_dir_pr)
    else:
        raise Exception("Error! Cannot locate: default.properties")

    # add and check classpaths
    jars = [corenlp_path +"/"+ jar for jar in jars]
    for jar in jars:
        if not os.path.exists(jar):
            raise Exception("Error! Cannot locate: %s" % jar)

    # add memory limit on JVM
    if memory:
        limit = "-Xmx%s" % memory
    else:
        limit = ""

    return "%s %s -cp %s %s %s" % (java_path, limit, ':'.join(jars), classname, props)


def remove_id(word):
    """Removes the numeric suffix from the parsed recognized words: e.g. 'word-2' > 'word' """
    return word.count("-") == 0 and word or word[0:word.rindex("-")]


def parse_bracketed(s):
    '''Parse word features [abc=... def = ...]
    Also manages to parse out features that have XML within them
    '''
    word = None
    attrs = {}
    temp = {}
    # Substitute XML tags, to replace them later
    for i, tag in enumerate(re.findall(r"(<[^<>]+>.*<\/[^<>]+>)", s)):
        temp["^^^%d^^^" % i] = tag
        s = s.replace(tag, "^^^%d^^^" % i)
    # Load key-value pairs, substituting as necessary
    for attr, val in re.findall(r"([^=\s]*)=([^=\s]*)", s):
        if val in temp:
            val = temp[val]
        if attr == 'Text':
            word = val
        else:
            attrs[attr] = val
    return (word, attrs)


def parse_parser_results(text):
    """ This is the nasty bit of code to interact with the command-line
    interface of the CoreNLP tools.  Takes a string of the parser results
    and then returns a Python list of dictionaries, one for each parsed
    sentence.
    """
    results = {"sentences": []}
    state = STATE_START
    for line in unidecode(text.decode('utf-8')).split("\n"):
        line = line.strip()

        if line.startswith("Sentence #"):
            sentence = {'words':[], 'parsetree':[], 'dependencies':[]}
            results["sentences"].append(sentence)
            state = STATE_TEXT

        elif state == STATE_TEXT:
            sentence['text'] = line
            state = STATE_WORDS

        elif state == STATE_WORDS:
            if not line.startswith("[Text="):
                raise ParserError('Parse error. Could not find "[Text=" in: %s' % line)
            for s in WORD_PATTERN.findall(line):
                sentence['words'].append(parse_bracketed(s))
            state = STATE_TREE

        elif state == STATE_TREE:
            if len(line) == 0:
                state = STATE_DEPENDENCY
                sentence['parsetree'] = " ".join(sentence['parsetree'])
            else:
                sentence['parsetree'].append(line)

        elif state == STATE_DEPENDENCY:
            if len(line) == 0:
                state = STATE_COREFERENCE
            else:
                split_entry = re.split("\(|, ", line[:-1])
                if len(split_entry) == 3:
                    rel, left, right = map(lambda x: remove_id(x), split_entry)
                    sentence['dependencies'].append(tuple([rel,left,right]))

        elif state == STATE_COREFERENCE:
            if "Coreference set" in line:
                if 'coref' not in results:
                    results['coref'] = []
                coref_set = []
                results['coref'].append(coref_set)
            else:
                for src_i, src_pos, src_l, src_r, sink_i, sink_pos, sink_l, sink_r, src_word, sink_word in CR_PATTERN.findall(line):
                    src_i, src_pos, src_l, src_r = int(src_i)-1, int(src_pos)-1, int(src_l)-1, int(src_r)-1
                    sink_i, sink_pos, sink_l, sink_r = int(sink_i)-1, int(sink_pos)-1, int(sink_l)-1, int(sink_r)-1
                    coref_set.append(((src_word, src_i, src_pos, src_l, src_r), (sink_word, sink_i, sink_pos, sink_l, sink_r)))

    return results

def parse_parser_xml_results(xml, file_name=""):
    import xmltodict
    from collections import OrderedDict

    def extract_words_from_xml(sent_node):
        exted = map(lambda x: x['word'], sent_node['tokens']['token'])
        return exted

    # Turning the raw xml into a raw python dictionary:
    raw_dict = xmltodict.parse(xml)
    document = raw_dict[u'root'][u'document']

    # Making a raw sentence list of dictionaries:
    raw_sent_list = document[u'sentences'][u'sentence']

    if document.get(u'coreference') and document[u'coreference'].get(u'coreference'):
        # Convert coreferences to the format like python
        coref_flag = True

        # Making a raw coref dictionary:
        raw_coref_list = document[u'coreference'][u'coreference']

        # To dicrease is for given index different from list index
        coref_index = [[[int(raw_coref_list[j][u'mention'][i]['sentence'])-1,
                         int(raw_coref_list[j][u'mention'][i]['head'])-1,
                         int(raw_coref_list[j][u'mention'][i]['start'])-1,
                         int(raw_coref_list[j][u'mention'][i]['end'])-1]
                        for i in xrange(len(raw_coref_list[j][u'mention']))]
                       for j in xrange(len(raw_coref_list))]

        coref_list = []
        for j in xrange(len(coref_index)):
            coref_list.append(coref_index[j])
            for k, coref in enumerate(coref_index[j]):
                exted = raw_sent_list[coref[0]]['tokens']['token'][coref[2]:coref[3]]
                exted_words = map(lambda x: x['word'], exted)
                coref_list[j][k].insert(0, ' '.join(exted_words))

        coref_list = [[[coref_list[j][i], coref_list[j][0]]
                        for i in xrange(len(coref_list[j])) if i != 0]
                      for j in xrange(len(coref_list))]
    else:
        coref_flag = False

    # Convert sentences to the format like python
    # TODO: If there is only one sentence in input sentence,
    # raw_sent_list is dict and cannot decode following code...
    sentences = [{'dependencies': [[dep['dep'][i]['@type'],
                                    dep['dep'][i]['governor']['#text'],
                                    dep['dep'][i]['dependent']['#text']]
                                   for dep in raw_sent_list[j][u'dependencies']
                                   for i in xrange(len(dep['dep']))
                                   if dep['@type']=='basic-dependencies'],
                  'text': extract_words_from_xml(raw_sent_list[j]),
                  'parsetree': str(raw_sent_list[j]['parse']),
                  'words': [[str(token['word']), OrderedDict([
                      ('NamedEntityTag', str(token['NER'])),
                      ('CharacterOffsetEnd', str(token['CharacterOffsetEnd'])),
                      ('CharacterOffsetBegin', str(token['CharacterOffsetBegin'])),
                      ('PartOfSpeech', str(token['POS'])),
                      ('Lemma', str(token['lemma']))])]
                            for token in raw_sent_list[j][u'tokens'][u'token']]}

                 for j in xrange(len(raw_sent_list)) ]

    if coref_flag:
        results = {'coref':coref_list, 'sentences':sentences}
    else:
        results = {'sentences': sentences}

    if file_name:
        results['file_name'] = file_name

    return results

def parse_xml_output(input_dir, corenlp_path="stanford-corenlp-full-2013-04-04/", memory="3g"):
    """Because interaction with the command-line interface of the CoreNLP
    tools is limited to very short text bits, it is necessary to parse xml
    output"""
    #First, we change to the directory where we place the xml files from the
    #parser:

    xml_dir = tempfile.mkdtemp()
    file_list = tempfile.NamedTemporaryFile()

    #we get a list of the cleaned files that we want to parse:

    files = [input_dir+'/'+f for f in os.listdir(input_dir)]

    #creating the file list of files to parse

    file_list.write('\n'.join(files))
    file_list.seek(0)

    command = init_corenlp_command(corenlp_path, memory)\
              + ' -filelist %s -outputDirectory %s' % (file_list.name, xml_dir)

    #creates the xml file of parser output:

    call(command, shell=True)

    #reading in the raw xml file:
    result = []
    try:
        for output_file in os.listdir(xml_dir):
            with open(xml_dir+'/'+output_file, 'r') as xml:
                # parsed = xml.read()
                file_name = re.sub('.xml$', '', os.path.basename(output_file))
                result.append(parse_parser_xml_results(xml.read(), file_name))
    finally:
        file_list.close()
        shutil.rmtree(xml_dir)
    return result

class StanfordCoreNLP:
    """
    Command-line interaction with Stanford's CoreNLP java utilities.
    Can be run as a JSON-RPC server or imported as a module.
    """
    def __init__(self, corenlp_path="stanford-corenlp-full-2013-04-04/", memory="3g"):
        """
        Checks the location of the jar files.
        Spawns the server as a process.
        """

        # spawn the server
        start_corenlp = init_corenlp_command(corenlp_path, memory)
        if VERBOSE: print start_corenlp
        self.corenlp = pexpect.spawn(start_corenlp)

        # show progress bar while loading the models
        if VERBOSE:
            widgets = ['Loading Models: ', Fraction()]
            pbar = ProgressBar(widgets=widgets, maxval=5, force_update=True).start()
        self.corenlp.expect("done.", timeout=20) # Load pos tagger model (~5sec)
        if VERBOSE: pbar.update(1)
        self.corenlp.expect("done.", timeout=200) # Load NER-all classifier (~33sec)
        if VERBOSE: pbar.update(2)
        self.corenlp.expect("done.", timeout=600) # Load NER-muc classifier (~60sec)
        if VERBOSE: pbar.update(3)
        self.corenlp.expect("done.", timeout=600) # Load CoNLL classifier (~50sec)
        if VERBOSE: pbar.update(4)
        self.corenlp.expect("done.", timeout=200) # Loading PCFG (~3sec)
        if VERBOSE: pbar.update(5)
        self.corenlp.expect("Entering interactive shell.")
        if VERBOSE: pbar.finish()

        # interactive shell
        self.corenlp.expect("\nNLP> ", timeout=3)

    def close(self, force=True):
        self.corenlp.terminate(force)

    def isalive(self):
        return self.corenlp.isalive()

    def __del__(self):
        # If our child process is still around, kill it
        if self.isalive():
            self.close()

    def _parse(self, text):
        """
        This is the core interaction with the parser.

        It returns a Python data-structure, while the parse()
        function returns a JSON object
        """

        # CoreNLP interactive shell cannot recognize newline
        if '\n' in text or '\r' in text:
            to_send = re.sub("[\r\n]", " ", text).strip()
        else:
            to_send = text

        # clean up anything leftover
        def clean_up():
            while True:
                try:
                    self.corenlp.read_nonblocking (8192, 0.1)
                except pexpect.TIMEOUT:
                    break
        clean_up()

        self.corenlp.sendline(to_send)

        # How much time should we give the parser to parse it?
        # the idea here is that you increase the timeout as a
        # function of the text's length.
        # max_expected_time = max(5.0, 3 + len(to_send) / 5.0)
        max_expected_time = max(300.0, len(to_send) / 3.0)

        # repeated_input = self.corenlp.except("\n")  # confirm it
        t = self.corenlp.expect(["\nNLP> ", pexpect.TIMEOUT, pexpect.EOF,
                                 "\nWARNING: Parsing of sentence failed, possibly because of out of memory."],
                                timeout=max_expected_time)
        incoming = self.corenlp.before
        if t == 1:
            # TIMEOUT, clean up anything left in buffer
            clean_up()
            print >>sys.stderr, {'error': "timed out after %f seconds" % max_expected_time,
                                 'input': to_send,
                                 'output': incoming}
            raise TimeoutError("Timed out after %d seconds" % max_expected_time)
        elif t == 2:
            # EOF, probably crash CoreNLP process
            print >>sys.stderr, {'error': "CoreNLP terminates abnormally while parsing",
                                 'input': to_send,
                                 'output': incoming}
            self.corenlp.close()
            raise ProcessError("CoreNLP process terminates abnormally while parsing")
        elif t == 3:
            # out of memory
            print >>sys.stderr, {'error': "WARNING: Parsing of sentence failed, possibly because of out of memory.",
                                 'input': to_send,
                                 'output': incoming}
            return

        if VERBOSE: print "%s\n%s" % ('='*40, incoming)
        try:
            results = parse_parser_results(incoming)
        except Exception, e:
            if VERBOSE: print traceback.format_exc()
            raise e

        return results

    def raw_parse(self, text):
        """
        This function takes a text string, sends it to the Stanford parser,
        reads in the result, parses the results and returns a list
        with one dictionary entry for each parsed sentence.
        """
        return self._parse(text)

    def parse(self, text):
        """
        This function takes a text string, sends it to the Stanford parser,
        reads in the result, parses the results and returns a list
        with one dictionary entry for each parsed sentence, in JSON format.
        """
        return json.dumps(self.raw_parse(text))


def batch_parse(input_folder, corenlp_path="stanford-corenlp-full-2013-04-04/", memory="3g"):
    """
    This function takes input files,
    sends list of input files to the Stanford parser,
    reads in the results from temporary folder in your OS and
    returns a generator object of list that consist of dictionary entry.
    ( The function needs xmltodict,
    and doesn't need init 'StanfordCoreNLP' class. )
    """
    if not os.path.exists(input_folder):
        raise Exception("Not exist input_folder")

    return parse_xml_output(input_folder, corenlp_path, memory)


if __name__ == '__main__':
    """
    The code below starts an JSONRPC server
    """
    from jsonrpclib.SimpleJSONRPCServer import SimpleJSONRPCServer
    VERBOSE = True
    parser = optparse.OptionParser(usage="%prog [OPTIONS]")
    parser.add_option('-p', '--port', default='8080',
                      help='Port to serve on (default 8080)')
    parser.add_option('-H', '--host', default='127.0.0.1',
                      help='Host to serve on (default localhost; 0.0.0.0 to make public)')
    parser.add_option('-S', '--corenlp', default="stanford-corenlp-full-2013-04-04",
                      help='Stanford CoreNLP tool directory (default stanford-corenlp-full-2013-04-04/)')
    options, args = parser.parse_args()
    # server = jsonrpc.Server(jsonrpc.JsonRpc20(),
    #                         jsonrpc.TransportTcpIp(addr=(options.host, int(options.port))))
    try:
        server = SimpleJSONRPCServer((options.host, int(options.port)))

        nlp = StanfordCoreNLP(options.corenlp)
        server.register_function(nlp.parse)

        print 'Serving on http://%s:%s' % (options.host, options.port)
        # server.serve()
        server.serve_forever()
    except KeyboardInterrupt:
        print >>sys.stderr, "Bye."
        exit()
