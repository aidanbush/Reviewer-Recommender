.PHONY: all data

all: proposal.pdf

# building with xelatex rather than pdflatex produces unusual output
%.pdf: %.tex
	latexmk -pdf -quiet "$*" || { cat "$*.log"; exit 1; }
	#gs -q -dNOPAUSE -dBATCH -dPDFSETTINGS=/prepress -sDEVICE=pdfwrite -sOutputFile=$*fonts.pdf $*.pdf
	#mv $*fonts.pdf $*.pdf

clean:
	latexmk -C
