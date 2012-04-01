.PHONY=production staging

production:
	appcfg.py update -A just-landed .

staging:
	appcfg.py update -A just-landed-staging .