The entry:
[Learn RAG From Scratch – Python AI Tutorial from a LangChain Engineer](https://www.youtube.com/watch?v=sVcwVQRHIc8)

### Context
I have an entry is formated as a markdown reference where
- the title is under square bracket **[title]** and
- the reference is under round brackers **(reference)**.

### Goal
Your goal is to generate file with summaries of the content for a given entry.

### HowTo Content
Now I am describing the steps to generate content of the file.

#### Case 1:
If is youtube reference then you need to generate  the following structure:
- **Prior to generating files**, ensure the following folders exist, create them if they don't:
    - **output/** folder for all outputs
    - **output/subtitle/** folder for storing YouTube subtitle files
    - **output/yt_generated/** folder for storing generated markdown files
- The file name is the **output/yt_generated/{title}.md**, where the title name that is extracted from the square bracket [title]
- The source information is retrieved from reference is under round brackers (reference) and saved to an intermediate subtitle file **output/subtitle/{title}.txt**
fabric -y "{reference}" --transcript-with-timestamps > "output/subtitle/{title}.txt"
- The **YouTube channel information** (author name and channel URL) should be extracted from the YouTube video page:
    - Extract the channel name (e.g., "freeCodeCamp.org")
    - Extract the channel URL (e.g., "https://www.youtube.com/@freecodecamp")
    - This can be done using yt-dlp or by parsing the YouTube video metadata
    - **Prefer handle format** (https://www.youtube.com/@username) over legacy channel ID format (https://www.youtube.com/channel/UC...)
    - Store these as variables: **author_name** and **channel_url**
- The **summary** of the content is obtain by running this bash command
cat "output/subtitle/{title}.txt" | fabric -p summarize
    - please make sure that the information under the <think></think> section is filtered out
- The **youtube_summary** of the content is obtain by running this bash command
cat "output/subtitle/{title}.txt" | fabric -p youtube_summary
    - please make sure that the information under the <think></think> section is filtered out
- The **extract_wisdom** of the content is obtain by running this bash command
cat "output/subtitle/{title}.txt" | fabric -p extract_wisdom
    - please make sure that the information under the <think></think> section is filtered out
- you need to aggregate the information **author_name**, **channel_url**, **summary**, **youtube_summary**, and **extract_wisdom** that you obtained in the following structure:


[{author_name}]({channel_url})

[Link]({reference})

---

{filtered summary}

---
---
---

{filtered youtube_summary}

---
---
---

{filtered extract_wisdom}

### HowTo Generate
Generate python code based on all the above instructions. The file is named youtube_summary_generator.md.
