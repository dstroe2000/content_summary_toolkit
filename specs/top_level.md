There is a batch file that contains the following types of entries:
- empty line
- youtube with the format [title](reference)
- blog with the format [title](reference)
- Markdown header that starts with #
- commentary that starts with \#
- separator that consists of 3 dashes ---

The processing of the youtube entries is specified in specs/youtube_entry.md; and the implementation is done in youtube_summary_generator.py.
The processing of the blog entries is specified in specs/blog_entry.md; and the implementation is done in blog_summary_generator.py.

The will be no processing for the empty line, Markdown header, commentary, and separator.

At the top level there will parsing the the batch file and there will be a call to the youtube summary generator or blog summary generator based on the entry type.

At the end of batch processing, a summary report should be displayed showing:
- Total lines processed
- Number of YouTube entries processed
- Number of blog entries processed
- Number of skipped lines
- Number of invalid format lines
- Number of errors encountered
- Success rate percentage
- Total time taken for the batch processing

