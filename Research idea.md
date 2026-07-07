# Urban Imageability and Geographic Knowledge in Vision-Language Models

Large Vision-Language Models (VLMs) are increasingly capable of interpreting visual information and reasoning about places, yet little is known about how they internally represent cities and urban environments. While humans develop mental maps of places through experience, forming cognitive representations of landmarks, districts, paths, and neighbourhoods, it remains unclear whether modern AI systems develop analogous forms of geographic knowledge.

This project investigates how vision-language models recognise and differentiate urban environments from street-level imagery. Drawing inspiration from Kevin Lynch’s theory of urban imageability and cognitive mapping, the study examines whether some cities and neighbourhoods are inherently more recognisable than others, and whether these patterns mirror those observed in human perception.

A large dataset of street-level images will be collected using the Google Street View API. Images will be sampled from cities with populations exceeding one million inhabitants and will include both highly iconic locations and ordinary residential, commercial, and peripheral urban areas. The resulting dataset will enable the analysis of geographic recognition at multiple spatial scales.

The study is designed to measure geographic knowledge encoded within the models themselves rather than their ability to retrieve information from external sources. Consequently, all experiments will be conducted using models operating without Retrieval-Augmented Generation (RAG), web search, or external document retrieval systems. Models will be required to infer location solely from the visual information contained in the image and the geographic knowledge embedded within their internal representations acquired during training.

The project consists of two complementary analyses.

The first analysis focuses on city recognition. Models will be presented with street-level images and asked to identify the city in which the image was taken. This component investigates whether some cities are systematically easier to recognise than others and whether recognition performance differs across world regions. Particular attention will be given to the role of iconic landmarks, urban form, and the broader cultural visibility of cities in global media and digital content.

The second analysis focuses on neighbourhood recognition. Models will be informed of the city in advance and asked to identify the neighbourhood or district depicted in the image. This component directly connects to Lynch’s notion of imageability by examining whether certain neighbourhoods possess distinctive visual identities that make them more recognisable than others. The study will explore whether the visual cues used by models resemble the landmarks, districts, nodes, edges, and paths that humans employ when constructing mental maps of cities.

Beyond measuring prediction accuracy, the project seeks to understand the relationship between urban imageability, cultural visibility, and AI geographic knowledge. A central hypothesis is that urban recognisability emerges from the interaction between two forces: the physical distinctiveness of urban environments and the degree to which places occupy a prominent position in collective cultural memory. In this sense, the project asks not only whether AI systems can recognise places, but also which places are most visible within the latent geographic representations learned by modern foundation models.

Research Questions

1. How accurately can vision-language models identify cities from street-level imagery?
2. How accurately can vision-language models distinguish neighbourhoods within the same city?
3. To what extent does recognition performance depend on iconic landmarks and visually distinctive urban features?
4. Do cities and neighbourhoods with higher imageability achieve higher recognition rates?
5. Are some regions of the world systematically more visible within AI models than others?
6. Is urban recognisability better explained by physical urban form, cultural visibility, or a combination of both?
7. Do vision-language models exhibit forms of geographic cognition analogous to human mental maps?
