From python:3.8.0-alpine3.10

RUN apk add --no-cache build-base bash bash-doc bash-completion subversion libpng shadow git libpng-dev openrc freetype freetype-dev lapack-dev curl postgresql-client \
	&& pip3 install --upgrade pip 

RUN groupadd -g 1000 appuser
RUN useradd -r -u 1000 -g 1000 appuser --home /app --no-create-home

RUN mkdir /app

COPY requirements.txt /app/.

WORKDIR /app

RUN pip3 install -r requirements.txt

COPY . /app

ENTRYPOINT ["bash"]

CMD ["run_and_results.sh"]
