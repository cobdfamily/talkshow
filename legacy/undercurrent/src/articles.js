const spider = require( '@cobd/spider' );
const curlFetch = require( './curl_fetch' );

const feeds = require( '../mappings/feeds.json' );

module.exports = {
getArticleForURL: async function( url )
{
let $article = await curlFetch.getHTMLForURL( url );

return {
audio: $article( '#tts' ).find( 'a' ).first().attr( 'href' )
};
},
getArticleForCategoryAtIndex: async function( category, articleIndex )
{
let allArticles = await this.getArticlesForCategory( category );

if( !allArticles[articleIndex] )
{
throw new Error( "No article found at this index" );
}

return {
...allArticles[articleIndex],
...await this.getArticleForURL( allArticles[articleIndex].link ),
offset: articleIndex,
ArticlesInCategory: allArticles.length
};
},
getArticleMetadataFromXML: async function( articleXML )
{

return {
title: articleXML.find( 'title' ).text().trim(),
author: articleXML.find( 'author' ).text().trim(),
published: articleXML.find( 'pubDate' ).text().trim(),
link: articleXML.find( 'guid' ).text()
};

},
getArticlesForCategory: async function( category )
{

if( !feeds[category] || !feeds[category].url )
{
throw new Error( "Invalid category" );
}

let $ = await spider.getXMLForURL( feeds[category].url );

let items = $( 'item' );

let articlesFromFeed = [];

for(let i=0;i<items.length;i++)
{
articlesFromFeed.push( await this.getArticleMetadataFromXML( items.eq( i ) ) );
}

return articlesFromFeed;
},
getAvailableCategories: async function()
{
let availableCategories = [];

for( const [key,value] of Object.entries( feeds ) )
{

availableCategories.push( {
name: value.name,
slug: key
});

}

return availableCategories;
}
};
