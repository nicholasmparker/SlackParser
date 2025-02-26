ok - some rules here:
1) We remove NO functionality methods, etc.. without discussing first
2) We use SIMPLE best practices
3) We do not try to refactor or change other parts of the code without discussing first
4) If we find an issue, lets add a test for it if possible
5) Our tests should be simple and test our actual functionality. They should be written simply as a safegaurd against regressions

The issues to fix:
1) After an upload when you click "start import" it starts the extraction, but the user gets no feedback on the frontend.
The backend IS returning progress updates so this should be straightforward to implement.
-1  | Extracting slack-export-TQBU4GKJL-8405378778178-1738772226/files/F05ML41MZPF/title.txt
web-1  | Progress: 50%
web-1  | Extracting slack-export-TQBU4GKJL-8405378778178-1738772226/files/F05ML41MZPF/image.png
web-1  | Progress: 50%
web-1  | Extracting slack-export-TQBU4GKJL-8405378778178-1738772226/
The data extracts to data/extracts which is great.  its a mounted volume.

2) Once the extraction is complete. the user gets no feedback that the import has completed.  Refreshing the page shows "importing" with "starting import" but it does not appear to be doing anything.
