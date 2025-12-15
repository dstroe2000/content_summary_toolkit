The entry:
[Article - More of Silicon Valley is building on free Chinese AI](https://www.nbcnews.com/tech/innovation/silicon-valley-building-free-chinese-ai-rcna242430)

### Context
I have an entry is formated as a markdown reference where
- the title is under square bracket **[title]** and
- the reference is under round brackers **(reference)**.

### Goal
Your goal is to generate file with summaries of the content for a given entry.

### HowTo Content
Now I am describing the steps to generate content of the file.

#### Case 1:
If is NOT a YouTube reference (YouTube URLs are skipped) then you need to generate the following structure:
- **Prior to generating files**, ensure the following folders exist, create them if they don't:
    - **output/** folder for all outputs
    - **output/blog/** folder for storing fetched blog content
    - **output/blog_generated/** folder for storing generated summary markdown files
- The file name is the **output/blog_generated/{title}.md**, where the title name that is extracted from the square bracket [title]
- The source information is retrieved from reference is under round brackers (reference) and saved to an intermediate blog file **output/blog/{title}.md**
fabric -u '{reference}' > 'output/blog/{title}.md'
- The **summary** of the content is obtain by running this bash command
cat 'output/blog/{title}.md' | fabric -p summarize
    - please make sure that the information under the <think></think> section is filtered out
- The **extract_wisdom** of the content is obtain by running this bash command
cat 'output/blog/{title}.md' | fabric -p extract_wisdom
    - please make sure that the information under the <think></think> section is filtered out
- you need to aggregate the information **summary** and **extract_wisdom** that you obtained in the following structure:


[Link]({reference})

---

{filtered summary}

---
---
---

{filtered extract_wisdom}

### HowTo Generate
Generate python code based on all the above instructions. The file is named blog_summary_generator.py.
