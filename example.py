import os
from nltk.tokenize import sent_tokenize
from corenlp import StanfordCoreNLP

# The directory in which the stanford core NLP .jar is located -- you have to
# download this from their website.
CORE_NLP_DIR = "stanford-corenlp-dir/"
PARSER = StanfordCoreNLP(CORE_NLP_DIR)

in_file = "sentences.txt"
text = open(in_file, 'r').read()
sentences = sent_tokenize(text)  # Break the text into sentences.
for i, sentence in enumerate(sentences):
	try:
		parse = PARSER.raw_parse(sentence)
		if i%50 == 0:
			print " Entered sentence " + str(i) + " of " + str(len(sentences))
		write_parse_products(parse['sentences'][0])
	except Exception:
		print "Error on sentence:\n\t " + sentence + " \n "
		pass

def write_parse_products(self, parse):
	words = parse['words']

	word_objects = []
	text = ""
	for i, word_info in enumerate(words):
		properties = word_info[1]
		token = word_info[0].lower().strip()
		surface = word_info[0].strip()
		pos = properties['PartOfSpeech']
		space_before = ""
		if i > 0:
			after_previous_word = int(words[i-1][1]['CharacterOffsetEnd'])
			space_before = " "*(int(properties['CharacterOffsetBegin']) -
				after_previous_word)
		text += space_before + surface

	raw_sentence = text.replace("(", "(").replace(")", ")").replace("``", "\"").replace("\"\"", "\"")

	for dependency_info in parse['dependencies']:
		relation_name = dependency_info[0]
		gov_index = int(dependency_info[2]) - 1
		gov = word_objects[gov_index]
		dep_index = int(dependency_info[4]) - 1
		dep = word_objects[dep_index]


