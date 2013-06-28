"""
A load balancing platform for the CoreNLP python server.
This allows us to keep multiple instances of the server open 
at different ports, and allow the same script to handle 
loadbalancing so client scripts need not worry about such logic.
"""

import os, requests, json, sys, jsonrpclib
from subprocess import Popen, PIPE
from hashlib import sha1

class CoreNLPLoadBalancer:
    def __init__(self, options):
        self.tempdir = "/tmp/"
        self.ports = options.ports.split(',')
        self.host = options.host
        self.serverPool = {}
        self.processPool = {}
        self.args = ["python", os.getcwd() + "/corenlp/corenlp.py", \
                    '--host=%s' % (options.host), \
                    '--properties=%s' % (options.properties), \
                    '--corenlp=%s' % (options.corenlp)]
        if not options.verbose:
            self.args += ['--quiet']
        self.portCounter = 0
        self.startup()

    def startup(self):
        """ Open a traditional server subprocess in a new port """
        for port in self.ports:
            self.serverPool[port] = Popen(self.args + ['--port=%s' % str(port)])

    def shutdown(self):
        for port in self.ports:
            self.serverPool[port].terminate()

    def sendThreadedRequest(self, key, port):
        """ Create a process that communicates with the server in a thread to avoid blocking """
        host = 'http://%s:%s' % (self.host.replace('http://', ''), port)
        filename = self.tempdir+key+".tmp"
        self.processPool[key] = Popen(['python', os.getcwd()+'/corenlp/subserver.py', host, filename], stdout=PIPE)

    def send(self, text):
        """ 
        Writes a temp file with the current text. The subserver script deletes this file for us. 
        The response sent provides a sha1 key that corresponds to your requested document so we 
        can correlate requests to responses.
        """
        currentPort = self.ports[self.portCounter]
        key = sha1(text).hexdigest()
        filename = self.tempdir+key+".tmp"
        f = open(filename, 'w')
        f.write(text)
        f.close()
        self.sendThreadedRequest(key, currentPort)
        return {'status':'OK', 'key':key}

    def getCompleted(self):
        """ Returns all completed parses. Set blocking to True on your last iteration to get all data """
        docResponse = {}
        response = {'status':'OK'}
        try:
            for key in self.processPool.keys():
                print key
                process = self.processPool[key]
                print process
                if process.poll() != None:
                    docResponse[key] = self.getForFinishedProcess(process)
                    del self.processPool[key]
        except:
            response['status'] = 'ERROR'
            response['error'] = sys.exc_info()[1]
        response['parses'] = docResponse
        return response

    def getAll(self):
        """ Blocking counterpart to getCompleted. Wait for all currently open processes to complete and send response. """
        response = {}
        for key in self.processPool.keys():
            response[key] = self.getForKey(key)
        return {'status':'OK', 'parses':response}

    def getForFinishedProcess(self, process):
        """ Returns a dictionary with json string or empty dictionary """
        response = {}
        print 'communicating'
        (out, error) = process.communicate()
        if out:
            try:
                response = json.loads(out)
            except:
                print sys.exc_info()
                pass
        return response

    def getForKey(self, key):
        """ Retrieves a response for a given key. This is blocking. """
        response = {}
        if key in self.processPool.keys():
            process = self.processPool[key]
            if process.poll == None:
                process.wait()
            response[key] = self.getForFinishedProcess(process)
        else:
            response[key] = {}
        return response
