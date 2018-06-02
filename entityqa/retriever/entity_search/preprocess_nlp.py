import json
import os
import spacy
import sqlite3
import time
import threading
import unicodedata
from datetime import datetime
from queue import Queue


# https://www.ploggingdev.com/2017/01/multiprocessing-and-multithreading-in-python-3/

# A copy of
# https://github.com/facebookresearch/DrQA/blob/master/drqa/retriever/doc_db.py
class DocDB(object):
    """Sqlite backed document storage.

    Implements get_doc_text(doc_id).
    """

    def __init__(self, db_path=None):
        self.path = db_path
        self.connection = sqlite3.connect(self.path, check_same_thread=False)

        cursor = self.connection.cursor()
        # # add 'p_ner_spacy' column to wiki_db
        # cursor.execute("ALTER TABLE documents ADD p_ner_spacy TEXT")
        cursor.execute("PRAGMA table_info(documents)")
        print(cursor.fetchall())
        cursor.close()

        # add index
        # cursor = wiki_db.connection.cursor()
        # cursor.execute("CREATE INDEX idx ON documents(id)")
        # cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def path(self):
        """Return the path to the file that backs this database."""
        return self.path

    def close(self):
        """Close the connection to the database."""
        self.connection.close()

    def get_doc_ids(self):
        """Fetch all ids of docs stored in the db."""
        cursor = self.connection.cursor()
        cursor.execute("SELECT id FROM documents")
        results = [r[0] for r in cursor.fetchall()]
        cursor.close()
        return results

    def get_doc_text(self, doc_id):
        """Fetch the raw text of the doc for 'doc_id'."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT text FROM documents WHERE id = ?",
            (unicodedata.normalize('NFD', doc_id),)
        )
        result = cursor.fetchone()
        cursor.close()
        return result if result is None else result[0]

    def get_doc_p_ents(self, doc_id):
        """Fetch the raw text of the doc for 'doc_id'."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT p_ner_spacy FROM documents WHERE id = ?",
            (unicodedata.normalize('NFD', doc_id),)
        )
        result = cursor.fetchone()
        cursor.close()
        return result if result is None else result[0]

    def update_ner_doc(self, doc_id, v):
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE documents SET p_ner_spacy=? WHERE id = ?",
            (v, unicodedata.normalize('NFD', doc_id))
        )
        cursor.close()


def preprocess_worker(doc_id):
    global wiki_db
    global nlp_spacy
    global doc_ids
    global doc_count
    global skipped_doc_count

    # skip already processed docs
    doc_p_ents = wiki_db.get_doc_p_ents(doc_id)
    if doc_p_ents is None:
        # with threading_lock:
        #     print('Already processed doc', doc_id)
        skipped_doc_count += 1
        return

    doc_text = wiki_db.get_doc_text(doc_id)
    paragraph_infos = list()

    paragraphs = doc_text.split('\n\n')
    for p_idx, p in enumerate(paragraphs):
        p_doc = nlp_spacy(p.strip())  # trim and nlp

        # NER
        ents = list()
        for entity in p_doc.ents:
            ents.append({'text': entity.text,
                         'start_char': entity.start_char,
                         'end_char': entity.end_char,
                         'label_': entity.label_})

        paragraph_info = {
            'text': p,
            'ents': ents
        }
        paragraph_infos.append(paragraph_info)

    with threading_lock:
        wiki_db.update_ner_doc(doc_id,
                               json.dumps({'paragraphs': paragraph_infos}))

        doc_count += 1
        if doc_count % 1000 == 0:
            print(datetime.now(), doc_count,
                  '(skipped {})'.format(skipped_doc_count))
            wiki_db.connection.commit()


n_threads = 8
wiki_db = DocDB(
    db_path=os.path.join(os.path.expanduser('~'), 'common', 'wikipedia',
                         'docs.db'))

# python3 -m spacy download en_core_web_lg
nlp_spacy = spacy.load('en_core_web_lg', disable=['parser', 'tagger'])
doc_ids = wiki_db.get_doc_ids()
print('# wiki docs', len(doc_ids))

doc_count = 0
skipped_doc_count = 0

threading_lock = threading.Lock()


def main():
    doc_queue = Queue()

    def process_queue():
        while True:
            preprocess_worker(doc_queue.get())
            doc_queue.task_done()

    for i in range(n_threads):
        t = threading.Thread(target=process_queue)
        t.daemon = True
        t.start()

    start = time.time()

    for doc_id in doc_ids:
        doc_queue.put(doc_id)

    doc_queue.join()

    print(threading.enumerate())

    print("Execution time = {0:.5f}".format(time.time() - start))

    wiki_db.close()


if __name__ == '__main__':
    main()
