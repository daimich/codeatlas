test:
	python3 -m unittest discover -s tests -v

demo:
	python3 -m codeatlas index examples/sample_repo
	python3 -m codeatlas serve

eval:
	python3 -m codeatlas index examples/sample_repo
	python3 -m codeatlas eval
