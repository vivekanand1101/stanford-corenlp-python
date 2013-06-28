"""
A load balancing platform for the CoreNLP python server.
This allows us to keep multiple instances of the server open 
at different ports, and allow the same script to handle 
loadbalancing so client scripts need not worry about such logic.
"""

import os, requests, json, sys, jsonrpclib
from subprocess import Popen
from hashlib import sha1

class CoreNLPLoadBalancer:
    def __init__(self, options):
        self.tempdir = "/tmp/"
        self.ports = options.ports.split(',')
        self.host = options.host
        self.serverPool = []
        self.processPool = {}
        self.args = ["python", os.getcwd() + "/corenlp.py", \
                    '--host=%s' % (options.host), \
                    '--properties=%s' % (options.properties), \
                    '--corenlp=%s' % (options.corenlp)]
        if not options.verbose:
            args += ['--quiet']
        self.portCounter = 0
        

    def startup(self):
        """ Open a traditional server subprocess in a new port """
        for port in self.ports:
            self.serverPool[port] = Popen(args + ['--port=%s' % str(port)])

    def shutdown(self):
        for port in self.ports:
            self.serverPool[port].terminate()

    def sendThreadedRequest(self, key, port):
        """ Create a process that communicates with the server in a thread to avoid blocking """
        host = 'http://%s:%s' % (self.host.replace('http://', ''), port)
        filename = self.tempdir+key+".tmp"
        self.processPool[key] = [Popen(['python', 'subserver.py', host, filename], stdout=PIPE)]

    def send(self, text):
        """ 
        Writes a temp file with the current text. The subserver script deletes this file for us. 
        The response sent provides a sha1 key that corresponds to your requested document so we 
        can correlate requests to responses.
        """
        currentPort = self.ports[self.portCounter]
        key = sha1(text)
        filename = self.tempdir+key+".tmp"
        f = open(filename, 'w')
        f.write(text)
        f.close()
        self.sendThreadedRequest(key, currentPort)
        return {'status':'OK', 'key':key}

    def receive(self, blocking=False):
        """ Returns all completed parses. Set blocking to True on your last iteration! """
        go = True
        response = []
        while go:
            for key in self.processPool.keys():
                process = self.processPool[key]
                if process.poll() != None:
                    (out, error) = process.communicate()
                    if out:
                        try:
                            response[key] = [json.loads(out)]
                        except:
                            pass
                    del self.processPool[key]
            go = blocking and len(self.processPool) > 0
        return response
