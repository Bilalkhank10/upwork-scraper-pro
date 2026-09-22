FROM apify/actor-python:3.12

COPY requirements.txt ./
RUN echo "Python version:" \
 && python --version \
 && echo "Pip version:" \
 && pip --version \
 && echo "Installing dependencies:" \
 && pip install -r requirements.txt \
 && echo "All installed!"

COPY . ./

CMD ["python", "-m", "src.main"]
